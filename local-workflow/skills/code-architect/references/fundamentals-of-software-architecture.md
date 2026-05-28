<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->
# Fundamentals of Software Architecture Reference
Source: Fundamentals of Software Architecture by Mark Richards & Neal Ford

## Table of Contents
- Architecture Characteristics (line ~12)
- Identifying & Measuring Characteristics (line ~100)
- Architecture Styles Overview (line ~145)
- Monolithic Styles (line ~165)
- Distributed Styles (line ~255)
- Choosing a Style (line ~400)
- Architecture Decisions (line ~440)
- Analyzing Risk (line ~500)

---

## Architecture Characteristics

Architecture characteristics (also called non-functional requirements or quality attributes) are design concerns that are NOT part of the domain functionality but are critical to system success. An architecture characteristic meets three criteria:
1. Specifies a non-domain design consideration
2. Influences some structural aspect of the design
3. Is critical or important to application success

**Critical rule**: Support the fewest architecture characteristics, not the most. Each one adds complexity.

### Operational Characteristics

| Characteristic | Definition |
|---|---|
| **Availability** | How long the system needs to be available. 24/7 requires redundancy and failover. |
| **Performance** | Response times, throughput, peak load handling. |
| **Scalability** | Ability to handle increasing users/requests. Differs from elasticity. |
| **Elasticity** | Ability to handle bursts of traffic. Spin up/down quickly. |
| **Reliability/Safety** | Fail-safe requirements. Mission-critical implications. |
| **Recoverability** | How quickly the system must recover from failure. Affects backup strategy. |
| **Robustness** | Handling errors, boundary conditions, network failures gracefully. |

### Structural Characteristics

| Characteristic | Definition |
|---|---|
| **Configurability** | End users can change software configuration through usable interfaces. |
| **Extensibility** | How important it is to add new functionality. |
| **Maintainability** | How easy to apply changes and enhance the system. |
| **Portability** | Does the system run on multiple platforms? |
| **Supportability** | Level of logging, debugging, technical support needed. |
| **Upgradeability** | Ease of upgrading to newer versions. |

### Cross-Cutting Characteristics

| Characteristic | Definition |
|---|---|
| **Accessibility** | Access for all users, including those with disabilities. |
| **Authentication** | Verifying user identity. |
| **Authorization** | Ensuring users can only access permitted functions/data. |
| **Feasibility** | Can this actually be built given constraints? |
| **Interoperability** | Integration with other systems. |
| **Legal** | Regulatory and legal constraints (GDPR, data sovereignty). |
| **Privacy** | Data privacy, encryption, PII handling. |
| **Security** | Protection against unauthorized access. |
| **Testability** | Ease of testing. Affects architecture structure. |
| **Usability** | Level of training and UX required. |

### Trade-offs

Architecture characteristics rarely exist in isolation. Improving one often degrades another. Common trade-offs:
- **Performance vs Scalability**: Optimizing for single-request speed can hurt horizontal scaling
- **Availability vs Consistency**: In distributed systems (CAP theorem)
- **Security vs Performance**: Encryption, authentication add latency
- **Simplicity vs Extensibility**: Abstractions add complexity upfront
- **Testability vs Performance**: Dependency injection adds indirection

**First Law of Software Architecture**: Everything in software architecture is a trade-off.

**Second Law**: Why is more important than how.

---

## Identifying & Measuring Characteristics

### Extracting from Requirements

Look for both explicit and implicit characteristics:
- **Explicit**: Stated in requirements ("must handle 10,000 concurrent users" = scalability)
- **Implicit**: Not stated but necessary for success (security for a payment system, availability for a trading system)

### From Domain Concerns

Translate domain priorities to architecture characteristics:
- "Time to market" → Agility, testability, deployability
- "User satisfaction" → Performance, availability, fault tolerance
- "Mergers and acquisitions" → Interoperability, scalability, adaptability, extensibility
- "Cost" → Simplicity, feasibility

### Measuring with Fitness Functions

A fitness function is an objective assessment of some architecture characteristic. Examples:
- Cyclic dependency check (modularity fitness function)
- Response time under load (performance fitness function)
- Deployment frequency (deployability fitness function)
- Code coverage thresholds (testability fitness function)
- Dependency direction checks (boundary fitness function)

Automate fitness functions in CI/CD pipelines to continuously verify architecture compliance.

### Component-Based Thinking

Architecture characteristics apply at the component level, not just system level. Different components may prioritize different characteristics:
- Payment component: Security, reliability
- Search component: Performance, elasticity
- Reporting component: Accuracy, recoverability

---

## Architecture Styles Overview

Architecture styles fall into two categories:

**Monolithic** (single deployment unit):
- Layered
- Pipeline
- Microkernel

**Distributed** (multiple deployment units):
- Service-Based
- Event-Driven
- Space-Based
- Orchestration-Driven SOA
- Microservices

### Fallacies of Distributed Computing

All distributed architectures must contend with these realities:
1. The network is NOT reliable
2. Latency is NOT zero
3. Bandwidth is NOT infinite
4. The network is NOT secure
5. The topology DOES change
6. There is NOT one administrator
7. Transport cost is NOT zero
8. The network is NOT homogeneous

Plus additional distributed challenges: distributed logging, distributed transactions, contract maintenance, versioning.

---

## Monolithic Architecture Styles

### Layered Architecture

**Topology**: Horizontal layers, typically presentation, business, persistence, database. Each layer has a specific role. Requests flow top-down.

**Key concepts**:
- **Closed layers**: A request must pass through each layer (no skipping). Provides isolation: changes in one layer don't ripple to others.
- **Open layers**: A layer can be bypassed. Use for shared services layers.
- **Layers of isolation**: The goal. Changes in one layer don't affect other layers.

**Characteristics ratings**:
- Cost: ★★★★★ (low cost, simple)
- Simplicity: ★★★★★ 
- Deployability: ★ (single deployment, all or nothing)
- Testability: ★★ (harder to mock layers)
- Scalability: ★ (can't scale layers independently)
- Fault tolerance: ★ (single point of failure)
- Elasticity: ★

**When to use**: Small applications, tight budgets, small teams, simple business logic. Good starting point when requirements are unclear.

**Anti-pattern**: Architecture sinkhole. Requests pass through layers doing nothing. If most requests are sinkholes, consider open layers or a different style.

### Pipeline Architecture

**Topology**: Pipes and filters. Data flows through a sequence of filters connected by pipes. Each filter transforms data independently.

**Filter types**:
- **Producer**: Starting point, outbound only (source)
- **Transformer**: Input, processing, output (map)
- **Tester**: Input, test, optional output (filter/reduce)
- **Consumer**: End point, inbound only (sink)

**Characteristics ratings**:
- Cost: ★★★★★
- Simplicity: ★★★★★
- Modularity: ★★★
- Deployability: ★★
- Testability: ★★★ (filters testable in isolation)
- Scalability: ★

**When to use**: ETL tools, data pipelines, shell scripting, simple one-way data processing.

### Microkernel Architecture (Plugin Architecture)

**Topology**: Core system + plugin modules. The core system contains minimal functionality. Plugins add features.

**Key concepts**:
- **Core system**: Minimal, stable, defines plugin interface
- **Plugin modules**: Independent, self-contained, add functionality
- **Registry**: Core system knows which plugins are available

**Plugin communication**: Plugins can be compile-time (linked at build) or runtime (loaded dynamically). Point-to-point between core and plugins. Plugins should NOT communicate with each other.

**Characteristics ratings**:
- Cost: ★★★★★
- Simplicity: ★★★★
- Testability: ★★★ (plugins testable in isolation)
- Modularity: ★★★
- Extensibility: ★★★★★ (add plugins without changing core)
- Deployability: ★★★ (if runtime plugins)
- Scalability: ★★

**When to use**: Product-based applications that need extensibility (IDE, browser, CI/CD tools). Applications where user-customizable features are needed. Clean Architecture's "plugin architecture" maps directly to this style.

---

## Distributed Architecture Styles

### Service-Based Architecture

**Topology**: Separately deployed coarse-grained services. Typically 4-12 services. Often share a single database. A UI layer connects to all services.

**Key concepts**:
- Services are domain-partitioned (not technically partitioned)
- Larger service granularity than microservices (each service is a mini-monolith)
- Database coupling is acceptable but should be managed
- Internal service structure follows layered architecture
- ACID transactions possible within a service

**Characteristics ratings**:
- Domain partitioning: ★★★★
- Deployability: ★★★★
- Testability: ★★★★
- Fault tolerance: ★★★★
- Scalability: ★★★
- Simplicity: ★★★
- Elasticity: ★★

**When to use**: Most practical distributed architecture. Good balance of distributed benefits without full microservices complexity. Teams of 4-12 developers. Moderate scalability needs.

### Event-Driven Architecture

**Topology**: Two main topologies: broker and mediator.

**Broker topology**: No central event mediator. Events are broadcast. Processors subscribe and react. Chain of events. Good for simple event flows.
- Highly decoupled
- Highly scalable
- Hard to trace, debug, and ensure processing order
- No error handling coordination

**Mediator topology**: Central event mediator coordinates event processing. Mediator knows the steps required for complex events.
- Better control and error handling
- Better coordination of complex workflows
- Mediator can become bottleneck and single point of failure
- Less decoupled than broker

**Characteristics ratings**:
- Performance: ★★★★★
- Scalability: ★★★★★
- Fault tolerance: ★★★★★
- Extensibility: ★★★★★
- Simplicity: ★ (complex to build and debug)
- Testability: ★★ (asynchronous flows hard to test)

**When to use**: High-throughput, highly scalable systems. Complex event processing. Systems where decoupling is paramount. Real-time processing.

### Space-Based Architecture

**Topology**: Designed to address scalability and concurrency issues. Uses in-memory data grids, replicated between processing units. No central database for operational data.

**Components**:
- **Processing unit**: Application logic + in-memory data grid
- **Virtualized middleware**: Manages processing units, data sync, request routing
- **Data pumps**: Async updates from in-memory grid to database for persistence
- **Data readers**: Read database data into in-memory grid on startup

**Characteristics ratings**:
- Elasticity: ★★★★★
- Scalability: ★★★★★
- Performance: ★★★★★
- Cost: ★ (expensive infrastructure)
- Simplicity: ★ (very complex)
- Testability: ★ (hard to simulate)

**When to use**: Extremely high volumes with unpredictable spikes. Concert/event ticketing, auction systems, social media at scale. When database bottleneck is the primary concern.

### Orchestration-Driven Service-Oriented Architecture (SOA)

**Topology**: Enterprise-level, service taxonomy with orchestration engine. Business services, enterprise services, application services, infrastructure services. Heavy middleware (ESB, orchestration engine).

**Characteristics**: Heavy, expensive, complex. Designed for enterprise integration of large systems. Largely superseded by microservices and service-based architectures.

**When to use**: Rarely for new systems. May encounter in legacy enterprise environments.

### Microservices Architecture

**Topology**: Fine-grained, independently deployable services. Each service is a bounded context. Each service owns its data (no shared database). Communication via REST, messaging, or gRPC.

**Key concepts**:
- **Bounded context**: Each service encapsulates a specific domain
- **Data isolation**: Each service has its own database/storage
- **Independently deployable**: Deploy one service without affecting others
- **API layer**: Optional, routes external requests to services
- **Sidecar pattern / service mesh**: Cross-cutting concerns (logging, monitoring, security)
- **Choreography vs orchestration**: Prefer choreography (event-based) for decoupling

**Characteristics ratings**:
- Deployability: ★★★★★
- Scalability: ★★★★★
- Fault tolerance: ★★★★★
- Modularity: ★★★★★
- Testability: ★★★★ (individual service testing is easy, integration testing is hard)
- Cost: ★ (expensive operationally)
- Simplicity: ★ (distributed systems complexity)
- Performance: ★★ (network overhead)

**When to use**: Large teams that need independent deployment. Systems requiring extreme scalability of individual components. Polyglot technology needs. When the operational cost is justified.

**Granularity**: The biggest challenge. Too fine-grained leads to excessive orchestration. Too coarse leads to a distributed monolith. Guidelines:
- Purpose: Does the service do one thing well?
- Transactions: If two services always transact together, consider merging
- Choreography: If you need extensive orchestration, services may be too fine

---

## Choosing a Style

There is no "best" architecture style. Selection depends on:

1. **Domain characteristics**: What does the business need? What are the domain's unique challenges?
2. **Architecture characteristics**: Which quality attributes matter most? (Pick 3-5 max)
3. **Data architecture**: How is data structured, shared, and managed?
4. **Organizational factors**: Team size, skill level, Conway's Law
5. **Knowledge of process, teams, and operational concerns**
6. **Domain/architecture isomorphism**: Does the architecture style match the domain naturally?

### Decision Matrix Approach

Rate each style against your prioritized architecture characteristics:

| Characteristic | Layered | Microkernel | Service-Based | Event-Driven | Microservices |
|---|---|---|---|---|---|
| Simplicity | ★★★★★ | ★★★★ | ★★★ | ★ | ★ |
| Deployability | ★ | ★★★ | ★★★★ | ★★★ | ★★★★★ |
| Testability | ★★ | ★★★ | ★★★★ | ★★ | ★★★★ |
| Scalability | ★ | ★★ | ★★★ | ★★★★★ | ★★★★★ |
| Extensibility | ★★ | ★★★★★ | ★★★ | ★★★★★ | ★★★ |
| Fault tolerance | ★ | ★★ | ★★★★ | ★★★★★ | ★★★★★ |
| Cost | ★★★★★ | ★★★★★ | ★★★ | ★★ | ★ |

### Monolith-First Strategy

For most new projects: start with a well-structured monolith (modular monolith or microkernel), then extract to distributed architecture when specific characteristics demand it. The cost of premature distribution is higher than the cost of later extraction, IF boundaries are clean.

---

## Architecture Decisions

### Architecture Decision Records (ADRs)

Document significant architecture decisions using ADRs. An ADR captures:
- **Title**: Short noun phrase (e.g., "Use Event-Driven Architecture for Order Processing")
- **Status**: Proposed, Accepted, Superseded
- **Context**: What forces are at play?
- **Decision**: What was decided and why?
- **Consequences**: What results from this decision? Both positive and negative.

### Anti-patterns in Decision Making

- **Covering Your Assets**: Avoiding decisions out of fear of being wrong. Make decisions with available information and be prepared to adapt.
- **Groundhog Day**: Revisiting the same decision repeatedly. Document decisions to prevent this.
- **Email-Driven Architecture**: Making decisions buried in email threads. Use ADRs.

### Good Decision Practices

- **Justify each decision**: Explain why, not just what. Reference architecture characteristics.
- **Consider alternatives**: Document what you considered and why you rejected alternatives.
- **Consult**: Get input from development teams. They have implementation knowledge.
- **Last responsible moment**: Delay decisions until you have enough information, but not so long that options close.

---

## Analyzing Risk

### Risk Assessment

Every architecture has risk. Continuously analyze and address it.

**Risk matrix**: Plot likelihood vs impact for each risk. Focus on high-likelihood, high-impact risks first.

**Risk storming**: Collaborative activity where the team identifies risks in the architecture:
1. Individually identify risks in the architecture diagram
2. Collaboratively discuss and consolidate
3. Prioritize and create mitigation plans

### Common Architecture Risks

- **Availability**: Single points of failure, missing redundancy
- **Data integrity**: Distributed transactions, eventual consistency issues
- **Scalability**: Bottlenecks, shared resources that don't scale
- **Performance**: Latency from network hops, serialization overhead
- **Security**: Attack surfaces, data in transit, authentication gaps
- **Deployability**: Complex deployment pipelines, deployment dependencies between services

### Risk Mitigation

- Address high-priority risks with architectural changes
- Document accepted risks with justification
- Create fitness functions to continuously monitor risk areas
- Review risk assessment regularly as the system evolves
