# Documented request service
## Modules
### API
`src/api.py` validates a request name before delegating storage to `src/store.py`.
### Store
`src/store.py` stores the validated name and returns its identifier.
## Threads
### Request Flow
The API validates a name, writes one record through Store, and returns the identifier. The README describes the same flow.
