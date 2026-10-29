# Code-only value service
## Modules
### Entry
`main.py` checks that `value` is an integer before calling `Store.save`.
### Store
`store.py` holds records in memory and returns the new record identifier.
## Threads
### Save Flow
`receive` reads `value`, rejects non-integers, and calls `Store.save` for accepted inputs.
