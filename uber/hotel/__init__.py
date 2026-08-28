"""Domain layer for hotel rooms - lottery-awarded and manually assigned.

Modules:
    queries   - read-only query/capacity helpers shared by every surface
    service   - room-assignment write path (create/edit, validation, audit)
    waitlist  - the waitlist engine (resize, FIFO fulfillment, accepts)
    solver    - the lottery award solver
    exports   - booking/inventory/waitlist exports (JSON API + spreadsheets)
    imports   - hotel confirmation/cancellation imports
    physical  - physical-room catalog, auto-assignment, rooming board
    pricing   - nightly rate resolution and stay totals
    audit     - room-data consistency checks (the Room Issues page)
    perms     - partition-scoped permission grants and audit trail

Transaction convention: modules in this package may session.flush() but
never session.commit() or rollback(). Route handlers, API methods, and
cron tasks own the transaction, and queue notification emails only after
their commit succeeds.
"""
