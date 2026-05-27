# Clean Architecture Reference
Source: Clean Architecture by Robert C. Martin

## Table of Contents
- SOLID Principles (line ~15)
- Component Principles (line ~120)
- Architecture & Boundaries (line ~210)
- Clean Architecture Pattern (line ~330)
- Details vs Policy (line ~400)

---

## SOLID Principles

The SOLID principles tell us how to arrange functions and data structures into classes and how those classes should be interconnected. They apply to any coupled grouping of functions and data, not just OOP classes. The goal: create mid-level software structures that tolerate change, are easy to understand, and form reusable components.

### SRP: Single Responsibility Principle

**Rule**: A module should be responsible to one, and only one, actor.

An "actor" is a group of users/stakeholders who require a change. SRP does NOT mean "do one thing" (that's a function-level rule). SRP means a class should only have one reason to change because it serves only one actor.

**Violation symptoms**:
- Accidental duplication: Two actors share a method (e.g., `calculatePay()` and `reportHours()` both call `regularHours()`). One actor's change breaks the other.
- Merge conflicts: Multiple developers changing the same file for different actors.

**Solutions**:
- Separate data from functions. Create separate classes for each actor's logic. Use Facade pattern if you need a single entry point.
- Example: Split `Employee` into `PayCalculator` (CFO), `HourReporter` (COO), `EmployeeSaver` (CTO), with `EmployeeFacade` for convenience.

**At higher levels**: SRP becomes Common Closure Principle (components) and Axis of Change (architectural boundaries).

### OCP: Open-Closed Principle

**Rule**: A software artifact should be open for extension but closed for modification.

If simple requirement changes force massive code changes, the architecture has failed. OCP is achieved by:
1. Separating things that change for different reasons (SRP)
2. Organizing dependencies so changes flow in one direction (DIP)

**Key pattern**: Partition into components where high-level policy is protected from low-level details. The Interactor (business rules) should know nothing about the Controller or the Presenters. Dependencies point toward the thing being protected.

**Dependency direction for protection**: If component A should be protected from changes in component B, then B should depend on A (not the other way around). The Interactor is the most protected component because it contains the highest-level business rules.

**Practical rule**: Arrange components in a hierarchy of protection. Business rules at the top (most protected), UI and database at the bottom (least protected). All source code dependencies point upward.

### LSP: Liskov Substitution Principle

**Rule**: If for each object o1 of type S there is an object o2 of type T such that for all programs P defined in terms of T, the behavior of P is unchanged when o1 is substituted for o2, then S is a subtype of T.

In practice: subtypes must be substitutable for their base types without breaking the program.

**Classic violation**: Square/Rectangle problem. If `Rectangle` has independent `setWidth` and `setHeight`, and `Square` overrides both to keep sides equal, code that sets width and height independently breaks.

**Architectural significance**: LSP applies beyond classes to interfaces, APIs, and services. If a REST service changes its contract subtly, all consumers can break. The architecture may need to add routing or adaptation mechanisms to handle non-compliant implementations.

**Rule for architects**: Design interfaces as contracts. All implementations must honor the full contract, not just the method signatures.

### ISP: Interface Segregation Principle

**Rule**: Don't depend on things you don't use.

If class A depends on class B through a fat interface, and A only uses 3 of B's 12 methods, A is coupled to 9 methods it doesn't need. Changes to those 9 methods can force A to recompile/redeploy.

**Solution**: Split the fat interface into client-specific interfaces. Each client depends only on the methods it actually calls.

**At the architectural level**: ISP warns against depending on frameworks or services that carry baggage you don't need. If system S depends on framework F, and F depends on database D, then S transitively depends on D, even if S doesn't use database features. A change in D can force redeployment of S.

**Rule**: Avoid depending on things that carry baggage you don't need. Prefer thin, focused interfaces.

### DIP: Dependency Inversion Principle

**Rule**: Depend on abstractions, not concretions. Source code dependencies should point toward abstractions, not toward concrete implementations.

Stable abstractions: Interfaces change less often than implementations. Every change to an interface requires changing all implementations. Every change to an implementation does NOT require changing the interface.

**Coding practices from DIP**:
- Don't refer to volatile concrete classes. Refer to abstract interfaces instead. Use Abstract Factories.
- Don't derive from volatile concrete classes.
- Don't override concrete functions (you inherit the dependencies). Make the function abstract, then create multiple implementations.
- Never mention the name of anything concrete and volatile in your source code.

**Factories**: The most volatile concrete creation must be handled carefully. Use Abstract Factory pattern: the application calls the factory interface, the implementation (in the low-level component) creates the concrete object, and returns it through the interface.

**Architectural rule**: The line between abstract/stable and concrete/volatile is the architectural boundary. All source code dependencies cross that boundary pointing toward the abstract side.

---

## Component Principles

Components are the units of deployment (jar, gem, dll, etc.). Component principles tell us which classes belong in which components and how components should relate.

### Cohesion Principles (what goes inside a component)

**REP (Reuse/Release Equivalence Principle)**: The granule of reuse is the granule of release. Classes and modules grouped into a component must belong to a cohesive group. They should be releasable together, sharing version numbers and release tracking.

**CCP (Common Closure Principle)**: Gather into components those classes that change for the same reasons and at the same times. Separate into different components those classes that change at different times or for different reasons. This is SRP for components. If a change comes, it should affect only one component, minimizing redeployment.

**CRP (Common Reuse Principle)**: Don't force users of a component to depend on things they don't use. This is ISP for components. If you depend on a component, you should need every class in it. Otherwise you'll be redeploying unnecessarily when unused classes change.

**The Tension Triangle**: REP and CCP make components bigger (inclusive). CRP makes components smaller (exclusive). Early in a project, favor CCP (develop-ability). As the project matures, shift toward REP (reusability). A good architect finds the right position in this tension triangle for the current phase.

### Coupling Principles (relationships between components)

**ADP (Acyclic Dependencies Principle)**: Allow no cycles in the component dependency graph. Cycles create a "morning after syndrome" where someone else's changes break your code. Two solutions for breaking cycles:
1. Apply DIP: Create an interface that the depended-on component owns, and have the other component implement it. This inverts the dependency.
2. Create a new component that both depend on, moving the shared classes into it.

**SDP (Stable Dependencies Principle)**: Depend in the direction of stability. A component that is hard to change should not depend on a component that is easy to change. Stability here means "difficulty of change", measured by the number of incoming vs outgoing dependencies.
- Stability metric I = Fan-out / (Fan-in + Fan-out). I=0 is maximally stable, I=1 is maximally instable.
- Not all components should be stable. If all are stable, the system is unchangeable.
- SDP says: each component's I metric should be larger than the I metrics of the components it depends on. Dependencies should flow toward stability.

**SAP (Stable Abstractions Principle)**: A component should be as abstract as it is stable. Stable components (hard to change) should be abstract so they can be extended. Unstable components (easy to change) should be concrete.
- Abstractness metric A = number of abstract classes / total classes.
- Plot components on I vs A graph. Components should fall near the "Main Sequence" line from (0,1) to (1,0).
- Zone of Pain: (0,0) = stable and concrete. Hard to change and can't extend. Avoid.
- Zone of Uselessness: (1,1) = unstable and abstract. No one depends on it. Wasted code.

---

## Architecture & Boundaries

### What Is Architecture?

The architecture of a software system is the shape given to that system by those who build it: the division into components, their arrangement, and their communication.

**Purpose**: Facilitate development, deployment, operation, and maintenance. The strategy: leave as many options open as possible, for as long as possible.

**Key insight**: Architecture has little bearing on whether a system works (plenty of terrible architectures work fine). Its real impact is on development cost, deployment ease, and maintenance burden.

**Policy vs Detail**: All systems decompose into policy (business rules, where true value lives) and details (IO, databases, web, frameworks). The goal: make policy agnostic to details so decisions about details can be delayed.

### Independence

A good architecture supports:
- **Use cases**: The architecture should scream the domain. Use cases should be first-class, visible elements.
- **Operation**: Isolate components so the system can transition between monolith, threads, processes, and services as needs change.
- **Development**: Partition into independently developable components so teams don't block each other (Conway's Law).
- **Deployment**: Aim for "immediate deployment" after build. No manual config scripts.

**Decoupling modes**:
- Source level: Control dependencies between modules. Monolith.
- Deployment level: Independently deployable units (jars, dlls). Still may run in single process.
- Service level: Dependencies are network calls. Micro/macro services.

A good architecture allows the system to start as a monolith and grow into services as needed, because the boundaries are already clean.

### Boundaries: Drawing Lines

A boundary separates things that matter from things that don't. The boundary line is drawn between the business rules and the database, between the business rules and the GUI, between the business rules and the framework.

**The Dependency Rule**: Source code dependencies always point toward the component containing the higher-level policy. The database knows about the business rules. The business rules do not know about the database.

**Plugin Architecture**: The database and the GUI are plugins to the business rules. This means the business rules can work with any database or any GUI. You can swap them without changing business logic.

**Boundary Anatomy**:
- Cheapest: Function calls across source-level boundaries (monolith).
- More expensive: Separate deployment components (jar/dll), communication through function calls but compiled/deployed independently.
- Most expensive: Services, communication through network calls.

**Partial Boundaries**: When a full boundary is too expensive, you can:
1. Prepare the interfaces and dependency structure but keep everything in one component.
2. Use one-dimensional boundaries (Strategy pattern instead of full reciprocal boundary).
3. Use Facade pattern: even simpler, but no dependency inversion.

### Business Rules

**Entities**: Enterprise-wide business rules. An entity is an object that embodies a set of critical business rules operating on critical business data. The entity does not know about the database, the UI, or any framework. It would exist even if there were no software system.

**Use Cases**: Application-specific business rules. A use case is an object that describes how an automated system is used. It contains the rules that specify how and when the critical business rules within the entities are invoked. Use cases control the dance of the entities.

**Use cases depend on entities. Entities do not depend on use cases.** Entities are the highest-level, most general rules. Use cases are closer to the application's specifics.

---

## The Clean Architecture Pattern

Concentric circles: inner circles are higher-level policy. Outer circles are mechanisms and details.

**Layers (inside out)**:
1. **Entities**: Enterprise business rules. The most general, highest-level rules.
2. **Use Cases**: Application business rules. Orchestrate entities.
3. **Interface Adapters**: Convert data between use case format and external format (controllers, presenters, gateways).
4. **Frameworks & Drivers**: The outermost layer. Database, web framework, UI framework. Glue code.

**The Dependency Rule**: Source code dependencies can only point inward. Nothing in an inner circle can know anything about an outer circle. This includes names, functions, classes, or any software entity.

**Data crossing boundaries**: When data crosses a boundary, it is always in a form convenient for the inner circle. Outer circles pass data as simple data structures. Inner circles never know about outer circle data formats (no ORM entities crossing into use cases).

**Typical flow**: Controller → Use Case Interactor → Entities → Use Case output → Presenter → View. Source code dependencies point inward at every step, even though the flow of control crosses boundaries in both directions (achieved via DIP at boundaries).

### Screaming Architecture

The architecture should scream the domain. When you look at the top-level directory structure, you should see the use cases of the system, not the framework. A health care system's architecture should look like a health care system, not like Rails or Spring.

**Test**: Can you look at the top-level source structure and tell what the system does? If you see `controllers/`, `models/`, `views/`, the architecture screams "framework." If you see `patients/`, `appointments/`, `prescriptions/`, the architecture screams "health care."

### Humble Object Pattern

At each architectural boundary, use the Humble Object pattern. Split behavior into two modules: one that is hard to test (the humble object, stripped of logic) and one that is easy to test (contains all testable behavior).

**Examples**:
- **Presenters/Views**: The View is the humble object (just displays data). The Presenter formats data into a ViewModel (testable without UI).
- **Database Gateways**: The Gateway implementation is the humble object (SQL). The interactor uses the Gateway interface (testable without database).
- **ORM**: The ORM is a database gateway in the data access layer. The entity objects used by business rules are SEPARATE from ORM entities.

---

## Details vs Policy

### The Database Is a Detail

From an architectural point of view, the database is a non-entity. It is a detail, a mechanism for storing and retrieving data. The data model is significant to the architecture, but the database technology is not.

The business rules don't need to know about the database schema, the query language, or any other technical detail of the database. The use cases and entities should use data access interfaces, and the database is just one possible implementation.

### The Web Is a Detail

The web is an IO device. The web is a delivery mechanism. The application should be deliverable through the web, through a thick client, through a console, or through any other mechanism. The business rules should not know they are being delivered over the web.

### Frameworks Are Details

Frameworks are powerful tools, but they ask you to marry them. They want you to couple your code to them. This is a one-directional relationship: the framework author doesn't know you exist.

**Rules for framework use**:
- Don't let frameworks into your inner circles.
- Treat the framework as a detail in the outer circle.
- Use the framework in the infrastructure/adapter layer, never in entities or use cases.
- Create proxy classes or adapters that your business rules depend on, and have those proxies delegate to the framework.

### The Test Boundary

Tests are part of the system. They follow the Dependency Rule. Tests depend on the code being tested. Nothing in the system depends on tests. Tests are the most isolated, outermost component.

**Fragile Tests Problem**: Tests that are coupled to the system's GUI, API structure, or implementation details break with every change. Solution: design for testability. Create a test API that bypasses volatile elements (GUI, security, etc.) and tests business rules directly.
