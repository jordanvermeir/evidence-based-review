# Paginated Pet Listing

## Context

Veterinary clinic staff and API consumers need to browse the pets registered in the clinic. As the number of pets grows, retrieving the entire list becomes inconvenient. Consumers need to request manageable portions of the list and navigate between them without losing track of the overall result set.

## Goal

Provide a paginated pet listing through the version 2 REST API, while maintaining the behavior of the existing pet-listing API for current consumers.

## Functional requirements

### Retrieving pets

**PET-001 — Paginated listing.** An API consumer can retrieve registered pets using `GET /api/v2/pets`. The response contains only the pets belonging to the requested page, rather than the complete collection.

**PET-002 — Page selection.** Consumers can specify the page using a zero-based `page` query parameter. Page `0` represents the first page; subsequent page numbers retrieve subsequent portions of the same ordered collection.

**PET-003 — Page size.** Consumers can specify the maximum number of pets returned using a positive integer `size` query parameter. The number of pets returned must not exceed the requested size. The final page may contain fewer pets.

**PET-004 — Default paging.** When `page` or `size` is omitted, the API applies a consistent documented default for that parameter. The response must make the effective paging values clear.

### Ordering and page consistency

**PET-005 — Consistent ordering.** Pets must be returned in a consistent order so that successive pages can be browsed predictably. Repeating the same request against unchanged data produces the same ordering.

**PET-006 — Name ordering.** Consumers can request that pets be ordered alphabetically by name, either ascending or descending. Ordering is applied across the entire matching collection *before* the requested page is selected. Pets with identical names must have a deterministic relative order, preventing duplicates or omissions when navigating pages against unchanged data. When no ordering preference is provided, the default ordering is used.

### Response information

**PET-007 — Pet details.** Each listed pet contains the pet information available to consumers of the existing pet-listing API. Pagination must not remove existing pet fields.

**PET-008 — Pagination metadata.** The response provides the current page number, configured page size, total number of matching pets, and total number of pages. Consumers can use this information to determine whether additional pages exist.

**PET-009 — Empty results.** When the clinic has no registered pets, the API returns a successful response with an empty pet list and coherent pagination metadata. A request for a page beyond the last available page also returns an empty list rather than pets from a different page.

### Compatibility and input handling

**PET-010 — Existing API compatibility.** The existing `GET /api/pets` endpoint retains its established behavior and response shape. Introducing the version 2 endpoint must not require existing consumers to change their requests.

**PET-011 — Invalid paging input.** Negative page numbers, non-positive page sizes, and non-numeric paging values are rejected with a client error rather than being silently interpreted as valid requests.

## Acceptance scenarios

**AC-01 — First page.** Given 45 registered pets, when a consumer requests `GET /api/v2/pets?page=0&size=20`, then the response contains 20 pets and reports 45 total pets across 3 pages.

**AC-02 — Final page.** Given the same 45 pets, when a consumer requests page 2 with size 20, then the response contains the remaining 5 pets.

**AC-03 — Different pages.** Given an unchanged collection, when a consumer requests consecutive pages of the same size and ordering, then pets do not appear on more than one page.

**AC-04 — Ascending names.** Given pets named Bella, Archie, Charlie, and Daisy, when the consumer requests ascending name ordering with page size 2, then the first page contains Archie and Bella, and the second contains Charlie and Daisy.

**AC-05 — Descending names.** Given the same pets, when the consumer requests descending name ordering with page size 2, then the first page contains Daisy and Charlie.

**AC-06 — Duplicate names.** Given multiple pets with the same name, when the consumer browses successive pages against unchanged data, then each pet appears exactly once.

**AC-07 — Empty clinic.** Given no registered pets, when the consumer requests the first page, then the result contains an empty list and reports zero total pets and zero total pages.

**AC-08 — Out-of-range page.** Given 45 registered pets, when the consumer requests page 9 with size 20, then the response contains an empty list and still reports the correct collection totals.

**AC-09 — Invalid page.** When the consumer requests a negative page number or a page size of zero, then the API returns a client error.

**AC-10 — Backward compatibility.** Given existing consumers using `GET /api/pets`, when the new paginated API becomes available, then the existing endpoint continues to return its established response.

## Out of scope

Creating, modifying, or deleting pets; filtering by owner or other attributes; and changes to existing pet records are outside this feature.
