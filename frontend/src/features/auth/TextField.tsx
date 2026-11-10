import { useId, type ComponentProps } from "react";

interface TextFieldProps extends Omit<ComponentProps<"input">, "id" | "className"> {
  label: string;
  /** Help under the field. */
  hint?: string;
}

/** A labelled input. The label is always visible and tied to the field. */
export function TextField({ label, hint, ...input }: TextFieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-semibold text-fg2">
        {label}
      </label>
      <input
        id={id}
        aria-describedby={hint ? hintId : undefined}
        className="w-full rounded-xl border border-hairline bg-transparent px-3 py-2 text-[15px] outline-none focus:border-accent"
        {...input}
      />
      {hint ? (
        <p id={hintId} className="text-xs text-fg2">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
