## Purpose

Keep already-persisted photo work moving in the hosted system while allowing a safe, authorized retry for one specified object.

## ADDED Requirements

### Requirement: Dokploy drains the existing photo queue
The Dokploy Compose stack SHALL run one CPU worker that repeatedly claims existing objects whose processing status is an awaiting status and whose photo key is non-empty. It SHALL use the existing database and schema initializer, the same MinIO endpoint/bucket credentials as the API, and the same persistent uploads volume as the API. It SHALL use the tracked `cv/ml/yolo-v/2-version.pt` checkpoint read-only, stay on the existing Compose default network, keep database and storage ports unpublished, and not use the separate ML dataset-reader proxy. Startup SHALL NOT seed records, reset rows, or rewrite database data.

#### Scenario: Existing awaiting rows are processed without an API restart
- **WHEN** the worker starts with a valid configured checkpoint and database connection
- **THEN** it polls and processes already-queued eligible rows using the existing status lifecycle
- **AND** it can read the original image through the existing private MinIO bucket and publish processed files through the shared uploads volume
- **AND** the worker exposes no host port and startup does not create demo rows or alter other objects

### Requirement: Reprocessing is restricted to one safe object
The authenticated API SHALL provide an operation that queues exactly one object identified in its path. It SHALL reject a missing object, an object without a worker-supported photo key, or an object already being processed. It SHALL serialize the requeue against the worker's row claim and change only that object's queue status, started timestamp, attempt count, and processing error. It SHALL NOT replace the photo, clear existing manual data, requeue other objects, or require a service restart.

#### Scenario: An eligible object is requeued
- **WHEN** an authenticated caller requests reprocessing for one existing object with a supported photo key that is not currently processing
- **THEN** only that row is set to `awaiting_processing` with a fresh attempt count and cleared queue error
- **AND** the persistent worker can claim it on its next polling cycle

#### Scenario: Requeue would overlap an active job
- **WHEN** the specified object is currently `processing`
- **THEN** the API rejects the request without changing the row

#### Scenario: Requeue is attempted without authorization or a supported photo
- **WHEN** the caller is unauthenticated with hosted authentication enabled, or the row lacks a supported photo key
- **THEN** the request is rejected and no queue state is changed

### Requirement: Generic pole localization is not reported as a cabinet defect
The `odn_pole` class SHALL map to a support-object detection without creating a defect record. Its outcome SHALL remain `check_required` because the class does not assess condition. The hosted worker SHALL use the actual compatible checkpoint metadata and SHALL NOT claim that its pole/manhole classes diagnose cabinets.

#### Scenario: Generic pole class is returned
- **WHEN** inference returns only the class `odn_pole`
- **THEN** the result identifies a support object requiring review, contains no defect for `odn_pole`, and does not report healthy or damaged cabinet condition

#### Scenario: Current checkpoint is used for photos of another asset type
- **WHEN** the existing checkpoint processes a cabinet photo
- **THEN** results are described only according to the checkpoint's actual `Broken`, `Good`, `Lose`, `Uncovered`, and pole/hardware class metadata
- **AND** no cabinet-specific conclusion is claimed
