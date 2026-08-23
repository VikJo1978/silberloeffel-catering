# Issue 150 fulfillment freeze compatibility rule

New OrderVersion operational-context snapshots freeze `fulfillment_mode` together with the delivery address.

Existing persisted snapshots stay semantically `UNKNOWN`; they are not rewritten from current Inquiry state. Legacy document creation may fall back to the current Inquiry fulfillment mode only when the frozen context mode is `UNKNOWN`.

Explicit OrderVersion changes inherit the parent snapshot's frozen fulfillment mode unless a future workflow explicitly models fulfillment as a deliberate order change.
