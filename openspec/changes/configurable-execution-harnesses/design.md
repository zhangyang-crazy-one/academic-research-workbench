## Context

The scheduler owns attempts, cancellation and deterministic result acceptance. The production CLI currently builds only independently qualified Codex adapters. Host identity v1 also names Codex directly. Configurable transports must preserve canonical records and the existing scientific gates.

## Goals / Non-Goals

Goals: select named native, command and API harnesses; preserve platform authentication; route all outputs through parent validation; keep current Codex proofs and legacy bytes readable.

Non-goals: claim every third-party CLI/API has been live-qualified, perform paid API tests during implementation, infer provider prices, or substitute model transcripts for proposals.

## Decisions

- Use a versioned configuration with named harnesses, a default and explicit assignment/role overrides. No CLI-brand or provider-name enumeration limits custom command drivers or registered application adapters. Native Codex continues through its existing exact-host qualification path.
- Command drivers receive a bounded, isolated request and return a versioned proposal/artifact envelope. On Linux the parent supplies a read-only namespace containing selected runtime roots and one fresh task directory; the canonical run and peer task directories are not mounted. Unsupported isolation fails before starting the driver.
- Built-in API drivers support OpenAI-compatible Responses and Chat Completions protocols. Other protocols use command drivers or application-registered adapters. A first-party worker performs stateless, non-streaming HTTP requests with explicit model/output bounds and no model tool execution. It cannot follow cross-origin redirects or execute response content. Secrets use named runtime variables or an explicit `.env`, never prompt/config literals or receipt values.
- The parent validates proposal identity/hash/nonce bindings and confined artifact bytes before creating immutable results. Context assembly uses only assignment-bound data; missing input content cannot silently become a successful research result.
- Capability evidence is platform-neutral. Versioned host identity v2 records harness/config/runtime/request bindings, while v1 remains unchanged. Backend selection alone cannot assert formal independence. Local process cancellation is bounded; remote inference cancellation remains provider-dependent and is reported accurately.
- Native development and Codex qualification remain gpt-6.1-sol/high. User-selected non-Codex platforms and API models use their own explicit configuration.

## Risks / Trade-offs

Third-party CLI formats differ: use the documented driver envelope or a small user-owned wrapper. Existing external credentials are copied only when explicitly selected, and are removed from fresh task homes. Live API availability and remote cancellation need deployment-specific qualification; loopback HTTP tests establish transport/parent behavior only.

## Migration Plan

Add configuration and adapters alongside the existing route, add v2 identity decoding and schemas without rewriting v1, verify real local command and HTTP transport behavior plus legacy replay, merge a dedicated PR, then build and qualify the final v0.2.0 main candidate.
