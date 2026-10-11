"""Trash/recycling schedule adapter — STUB.

Baltimore DPW does not publish a public API for address-level trash and
recycling collection schedules (as of this writing). Implementation paths:

1. Scrape the DPW collection-schedule pages/PDFs (fragile; check the site's
   terms of use first).
2. Partner with the city for a proper data feed (best long-term path, and a
   natural ask once a pilot relationship exists).
3. Crowdsource a static address -> schedule table for a pilot neighborhood.

Until one of these is implemented, get_trash_schedule raises
NotImplementedError with guidance instead of returning invented data.
"""


class SanitationAdapter:
    """Address-level trash/recycling schedules (not yet implemented)."""

    async def get_trash_schedule(self, address: str) -> dict[str, str]:
        raise NotImplementedError(
            "Trash/recycling schedules are not implemented: Baltimore DPW has no "
            "public API for address-level collection schedules. See this module's "
            "docstring for implementation paths."
        )
