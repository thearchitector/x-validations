# Validate the base schema before rules

The Validation Engine validates a payload against the Base Schema before evaluating X-Validation Rules, and returns no rule errors when base validation fails. Within the active stage it collects all errors and orders them deterministically, preventing rule evaluation from operating on payloads that violate its structural assumptions.
