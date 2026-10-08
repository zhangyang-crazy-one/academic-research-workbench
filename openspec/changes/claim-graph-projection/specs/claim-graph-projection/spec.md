## ADDED Requirements

### Requirement: Multi-log snapshot consistency
The graph SHALL validate original hash chains and semantic replay at explicit fixed run/journal prefixes, include all cross-log dependencies, and compare the entire vector for current reads. Historical views SHALL ignore unrelated later heads. The expected head SHALL be the snapshot manifest digest.

#### Scenario: A current log advances
- **WHEN** only a run or only the journal advances during a current projection
- **THEN** the projection reports stale

#### Scenario: A fixed historical view
- **WHEN** unrelated later events or a later torn tail exist
- **THEN** the fixed prefix reconstructs identical bytes and dependencies outside it report dependency_outside_prefix

### Requirement: Occurrence and claim identities
Occurrence nodes SHALL separately bind number, figure/caption or cited sentence UTF-8 bytes. Semantic claims SHALL carry explicit revision/predecessor identities; repeated sentences and multiple propositions SHALL never merge automatically. Versioned historical citation spans SHALL be reused without resegmentation.

#### Scenario: Repetition and multiple propositions
- **WHEN** a multibyte cited sentence repeats and is registered to two semantic claims
- **THEN** occurrence offsets remain distinct and expressions target only explicit claim revisions

### Requirement: Independent evidence dimensions and coverage
The graph SHALL project accepted parent/journal anchors through original adapters, retain independent integrity/check/relation/assessment/attestation dimensions, disclose scope, denominator, unknown and unsupported coverage, and preserve unknown AI involvement for imported manuscripts.

#### Scenario: Metadata passes and evidence contradicts
- **WHEN** a DOI metadata check passes with a contradicts edge
- **THEN** checks remain passed and the relation remains contradicts without a supported summary

### Requirement: Declared preceding-snapshot confirmations
Declared confirmations SHALL append through the project journal, reference only the N-1 snapshot, and bind exact claim revision/digest plus evidence dependency digest. Changed revisions or evidence SHALL make historical confirmations stale. Direction decisions SHALL not substitute for attestations. Hard coverage checks SHALL remain unavailable until authenticated contracts are implemented.

#### Scenario: Claim or evidence changes
- **WHEN** related wording becomes caused wording or its evidence dependency changes
- **THEN** previous declared confirmation remains historical and is stale for the current claim

#### Scenario: No self reference
- **WHEN** confirmation N is appended
- **THEN** its embedded snapshot journal prefix ends at N-1 and does not hash itself

### Requirement: Exact numeric and Figure proof composition
The public graph SHALL consume the original result_plot verifier at fixed real prefixes through a composition callback. Without it the kernel SHALL report typed unsupported. Own-result numbers SHALL resolve their accepted sealed request or verified plot value and explicit display; unknown IDs, incorrect plot context and unsupported calculations SHALL not become exact or passed. Numeric verdicts SHALL stay bound to individual claim revisions.

#### Scenario: Equal display with different exact context
- **WHEN** A and B both display 0.83 but have different exact values and derivation identities
- **THEN** an A occurrence referring to B's derivation fails even if the display text is equal

### Requirement: Caption target confirmation without digest cycles
Caption authentication SHALL bind a frozen semantic target excluding confirmation handles. Only a real canonical journal confirmation and accepted parent anchor with unchanged scope/claim/evidence SHALL yield authentication. The complete current IR hash SHALL be checked independently.

#### Scenario: A real authenticated target
- **WHEN** confirmation references are added after confirming the independently frozen target
- **THEN** target identity remains unchanged and the original writer can accept the exact hard-caption binding

#### Scenario: A caller label
- **WHEN** a declared record or unanchored handle is labeled authenticated in an IR
- **THEN** the true verifier reports auth_missing
