"""The worst-case chain names no facility, even when a tool's text quotes one."""

from __future__ import annotations

from api.schemas.workspace import Chemical, Facility, ScenarioDriver
from api.services.exposure_graph.worst_case import build_worst_case_chain
from tests.api.services.exposure_graph.factories import (
    EXPOSURE,
    PEOPLE,
    TEXT,
    WORKER,
    facility,
    stack_dict,
)

NAME = "Zyxwvut Chemical Works"
FRS = "110987654321"
DOC = "DOCCTRL-7788"
ADDRESS = "4242 Quuxbar Boulevard"
CITY = "Wibblesworth"
STATE = "ZQ"
ZIP = "98765"
INDUSTRY = "Plumbago Refining"
IDENTIFIERS = (NAME, FRS, DOC, ADDRESS, CITY, STATE, ZIP, INDUSTRY)


TRACT = "99001000100"
LATITUDE = 41.573129
LONGITUDE = -71.190877
BEARING = 123.456


def _scenario() -> dict[str, object]:
    tract = {
        "kind": "tract",
        "label": TRACT,
        "residents": 500,
        "distance_m": 480.0,
        "bearing_deg": BEARING,
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "fraction_of_maximum": 0.75,
    }
    return {
        "pathway_key": "community_inhalation",
        "pathway": "p",
        "quantity": "hq",
        "quantity_label": "Hazard quotient",
        "value": 1.0,
        "receptors": [tract, {**tract, "label": "99001000200", "residents": 70}],
        "receptors_note": f"Tracts within reach of {CITY} only",
        "notes": ["A scenario note", f"{NAME} is the nearest source"],
    }


def _plant() -> Facility:
    stack = {**stack_dict(1, 3.0), "warnings": [f"Stack data from the {NAME} permit"]}
    people = {**PEOPLE, "source": f"Census near {CITY}", "warnings": [f"{ADDRESS} is rural"]}
    worker = {**WORKER, "warnings": [f"{FRS} had a recorded exceedance"]}
    return facility(
        frs_id=FRS,
        name=NAME,
        doc_ctrl_num=DOC,
        address=ADDRESS,
        city=CITY,
        state=STATE,
        zip_code=ZIP,
        naics_subsector_title=INDUSTRY,
        stacks=[stack],
        exposure={**EXPOSURE, "warnings": [f"Modelled for {NAME}"]},
        receptors=people,
        occupational_exposure=worker,
        scenarios=[_scenario()],
    )


def _drivers() -> list[ScenarioDriver]:
    return [
        ScenarioDriver(
            pathway_key=pathway,
            quantity=quantity,
            frs_id=FRS,
            facility_name=NAME,
            stack_number=stack,
            value=1.0,
        )
        for pathway, quantity, stack in (
            ("community_inhalation", "hq", 1),
            ("worker_inhalation", "oel_ratio", None),
        )
    ]


def _json() -> str:
    chain = build_worst_case_chain([_plant()], _drivers(), TEXT, Chemical(cas_number="71-43-2"))
    return chain.model_dump_json()


def test_no_identifier_of_the_facility_is_in_the_serialised_chain() -> None:
    text = _json().lower()
    assert [i for i in IDENTIFIERS if i.lower() in text] == []


def test_the_chain_is_still_drawn_after_the_text_is_dropped() -> None:
    text = _json()
    assert "community:stack:1" in text and "worker:endpoint" in text
    assert "Census near" not in text


def test_tract_labels_and_coordinates_are_not_in_the_chain() -> None:
    text = _json()
    for hidden in (TRACT, "99001000200", str(LATITUDE), str(LONGITUDE), str(BEARING)):
        assert hidden not in text


def test_the_most_affected_tracts_keep_their_values_without_their_location() -> None:
    chain = build_worst_case_chain([_plant()], _drivers(), TEXT, Chemical(cas_number="71-43-2"))
    (band,) = [n for n in chain.nodes if n.id.startswith("community:band:")]
    values = {q.key: q.value for q in band.quantities}
    assert values["tract_residents:1"] == 500.0 and values["tract_residents:2"] == 70.0
    assert values["tract_distance:1"] == 480.0 and values["tract_fraction:1"] == 0.75
    assert [f.key for f in band.facts if f.key == "receptors_note"] == ["receptors_note"]
    end = next(n for n in chain.nodes if n.id == "community:endpoint")
    assert end.warnings == ["A scenario note"]


def test_the_default_community_lane_carries_no_tracts() -> None:
    from api.services.exposure_graph.community import community_lane

    parts = community_lane(_plant(), TEXT)
    keys = {q.key for n in parts.nodes for q in n.quantities}
    assert not {k for k in keys if k.startswith("tract_")}


def test_a_step_title_that_quotes_the_facility_is_withheld() -> None:
    plant = _plant()
    worker = plant.occupational_exposure
    assert worker is not None and worker.driving_activity is not None
    driving = worker.driving_activity.model_copy(update={"label": f"Drums at {NAME}"})
    quoted = worker.model_copy(update={"driving_activity": driving})
    plant = plant.model_copy(update={"occupational_exposure": quoted})
    chain = build_worst_case_chain([plant], _drivers(), TEXT, Chemical(cas_number="71-43-2"))
    release = next(n for n in chain.nodes if n.id == "worker:release")
    assert release.title == TEXT.worst_case.withheld_title
    assert NAME.lower() not in chain.model_dump_json().lower()
