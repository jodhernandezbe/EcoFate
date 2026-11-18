1. Create the Oracle Cloud account (the step that takes longest):
- Sign up at https://signup.cloud.oracle.com. It asks for a card to verify identity; Always Free resources aren't charged.
- Choose the home region carefully: it can't be changed later. Pick one near you or your reviewers. Popular regions often run out of the free ARM machines ("out of host capacity"). I can't tell you which regions currently have spare capacity, but if you can't create the VM later, that's the usual reason.

2. Protect yourself from charges and from VM reclamation (in the Oracle console, once the account is active):
- Upgrade the account to Pay As You Go. Within Always Free limits you still pay $0, and Oracle then stops reclaiming idle free VMs. It may run a small temporary authorisation on your card.
- Create a budget alert at $1 under Billing → Budgets, so any accidental paid resource emails you right away.

3. Let the provisioning script talk to Oracle, on your Mac:
- Install the OCI command-line tool: ! brew install oci-cli
- Run ! oci setup config. It asks for your user and tenancy IDs (OCIDs, found in the console under your profile) and your home region, then creates an API key. It prints a public key that you paste into the console under Profile → API keys.
- Check that it works with ! oci iam region list.

4. Cloudflare email sending: in the Cloudflare dashboard for ecofate.org, check whether Email Service → Sending can be enabled. Email Routing, which you already turned on, only receives mail. If sending isn't available, tell me and we'll use Resend's free tier.
