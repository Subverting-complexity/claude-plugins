# Design Patterns Reference
Source: Design Patterns: Elements of Reusable Object-Oriented Software (Gang of Four)

## Table of Contents
- When to Use Patterns (line ~12)
- Creational Patterns (line ~30)
- Structural Patterns (line ~120)
- Behavioral Patterns (line ~220)
- Pattern Selection Guide (line ~370)

---

## When to Use Patterns

Design patterns are solutions to recurring design problems. They are not templates to apply blindly. Every pattern involves trade-offs. Use a pattern when:
- You have a specific design problem the pattern solves
- The flexibility the pattern provides is worth the added complexity
- You expect the code to change in ways the pattern accommodates

Do NOT use a pattern when:
- The simpler approach works and you don't need the flexibility
- You're adding abstraction "just in case"
- The pattern makes the code harder to understand for the team

---

## Creational Patterns

Creational patterns abstract the instantiation process. They help make a system independent of how its objects are created, composed, and represented.

### Abstract Factory

**Intent**: Provide an interface for creating families of related objects without specifying concrete classes.

**Use when**:
- A system should be independent of how its products are created
- A system should work with multiple families of products
- Related products are designed to be used together and you need to enforce that constraint

**Structure**: AbstractFactory declares creation methods. ConcreteFactory implements them for a specific family. Client uses only the abstract interfaces.

**Architecture relevance**: Core to DIP. Business rules depend on the factory interface. Infrastructure provides concrete factory implementations. Essential for testability (test factories return mocks/stubs).

**Example**: `PaymentGatewayFactory` interface with `StripeFactory` and `PayPalFactory` implementations. Business logic calls `factory.createProcessor()` without knowing which provider.

### Builder

**Intent**: Separate the construction of a complex object from its representation so the same construction process can create different representations.

**Use when**:
- Object creation involves many steps or complex configuration
- You need to create different representations of the same thing
- Construction must happen step by step

**Architecture relevance**: Useful for constructing complex domain objects, configuration objects, or DTOs that cross boundaries.

### Factory Method

**Intent**: Define an interface for creating an object, but let subclasses decide which class to instantiate.

**Use when**:
- A class can't anticipate the class of objects it must create
- A class wants its subclasses to specify the objects it creates
- You want to localize the knowledge of which class gets created

**Architecture relevance**: Lighter than Abstract Factory. Good for single creation points. Subclasses provide the concrete implementation.

### Prototype

**Intent**: Specify the kinds of objects to create using a prototypical instance, and create new objects by copying this prototype.

**Use when**:
- Classes to instantiate are specified at runtime
- You want to avoid building a class hierarchy of factories
- Instances of a class have only a few different combinations of state

### Singleton

**Intent**: Ensure a class has only one instance and provide a global point of access.

**Use with extreme caution**:
- Creates global state, which makes testing hard
- Creates hidden dependencies
- Violates SRP (the class manages its own lifecycle AND its business logic)
- Often a sign that dependency injection is missing

**When genuinely needed**: True infrastructure singletons (connection pools, thread pools) managed by DI containers, not by the class itself.

---

## Structural Patterns

Structural patterns deal with how classes and objects are composed to form larger structures.

### Adapter

**Intent**: Convert the interface of a class into another interface clients expect. Lets classes work together that couldn't otherwise because of incompatible interfaces.

**Use when**:
- You want to use an existing class but its interface doesn't match what you need
- You want to create a reusable class that cooperates with unrelated classes
- You need to use several existing subclasses but can't adapt each by subclassing

**Architecture relevance**: Essential at boundaries. The Interface Adapter layer in Clean Architecture is full of adapters. Database gateways, API clients, message queue wrappers are all adapters.

**Example**: `StripePaymentAdapter` implements `PaymentGateway` interface, internally delegates to Stripe SDK. Business logic depends on `PaymentGateway`, not Stripe.

### Bridge

**Intent**: Decouple an abstraction from its implementation so the two can vary independently.

**Use when**:
- You want to avoid a permanent binding between abstraction and implementation
- Both abstractions and implementations should be extensible by subclassing
- Changes in implementation should have no impact on clients

**Architecture relevance**: Useful when a domain concept has multiple implementation strategies. Separates "what" from "how."

### Composite

**Intent**: Compose objects into tree structures to represent part-whole hierarchies. Clients treat individual objects and compositions uniformly.

**Use when**:
- You want to represent part-whole hierarchies
- Clients should be able to ignore the difference between single objects and groups

**Example**: File system (files and directories), organization charts, menu systems, permission trees.

### Decorator

**Intent**: Attach additional responsibilities to an object dynamically. Flexible alternative to subclassing for extending functionality.

**Use when**:
- You need to add responsibilities to individual objects, not the whole class
- You want to add/remove responsibilities at runtime
- Subclassing would cause an explosion of subclass combinations

**Architecture relevance**: Follows OCP. Add behavior without modifying existing code. Common for cross-cutting concerns: logging decorators, caching decorators, retry decorators, authorization decorators.

**Example**: `LoggingRepository` wraps `PostgresRepository`. Both implement `UserRepository`. The decorator adds logging around every call without modifying the real implementation.

### Facade

**Intent**: Provide a unified interface to a set of interfaces in a subsystem. Defines a higher-level interface that makes the subsystem easier to use.

**Use when**:
- You want to provide a simple interface to a complex subsystem
- There are many dependencies between clients and implementation classes
- You want to layer your subsystems

**Architecture relevance**: Use at module boundaries to simplify cross-module communication. A Facade does NOT enforce isolation (clients can still bypass it), so combine with DIP for true boundaries.

### Flyweight

**Intent**: Use sharing to support large numbers of fine-grained objects efficiently.

**Use when**:
- An application uses a large number of objects
- Storage costs are high because of the sheer quantity
- Most object state can be made extrinsic (passed in rather than stored)

### Proxy

**Intent**: Provide a surrogate or placeholder for another object to control access to it.

**Types**:
- **Remote Proxy**: Local representative for an object in a different address space
- **Virtual Proxy**: Creates expensive objects on demand (lazy loading)
- **Protection Proxy**: Controls access based on permissions
- **Smart Reference**: Adds behavior when an object is accessed (reference counting, logging)

**Architecture relevance**: Used at boundaries. A repository interface is a proxy for database access. A service client is a proxy for a remote service.

---

## Behavioral Patterns

Behavioral patterns deal with algorithms, assignment of responsibilities between objects, and communication patterns.

### Chain of Responsibility

**Intent**: Avoid coupling the sender of a request to its receiver by giving more than one object a chance to handle it. Chain receivers and pass the request along until one handles it.

**Use when**:
- More than one object may handle a request, and the handler isn't known in advance
- You want to issue a request to one of several objects without specifying the receiver
- The set of handlers should be dynamically configurable

**Example**: Middleware pipelines, validation chains, approval workflows.

### Command

**Intent**: Encapsulate a request as an object, allowing parameterization of clients with different requests, queueing, logging, and undo.

**Use when**:
- You need to parameterize objects with an action to perform
- You need to queue, log, or support undo/redo of requests
- You need to support transactions (execute a sequence, roll back on failure)

**Architecture relevance**: Foundation for CQRS (Command Query Responsibility Segregation). Commands cross boundaries as simple data structures.

### Iterator

**Intent**: Provide a way to access elements of a collection sequentially without exposing the underlying representation.

**Use when**: You need to traverse a collection without depending on its structure.

### Mediator

**Intent**: Define an object that encapsulates how a set of objects interact. Promotes loose coupling by preventing objects from referring to each other explicitly.

**Use when**:
- A set of objects communicate in well-defined but complex ways
- Reusing an object is difficult because it refers to many other objects
- You want to customize behavior distributed between several classes without subclassing

**Architecture relevance**: Use cases in Clean Architecture act as mediators between entities. Event buses are mediators. Orchestrators in service architectures are mediators.

### Memento

**Intent**: Capture and externalize an object's internal state so it can be restored later, without violating encapsulation.

**Use when**: You need undo, snapshots, or state rollback.

### Observer

**Intent**: Define a one-to-many dependency so that when one object changes state, all dependents are notified and updated automatically.

**Use when**:
- A change to one object requires changing others, and you don't know how many
- An object should notify other objects without being tightly coupled to them

**Architecture relevance**: Foundation for event-driven architectures. Domain events, pub/sub systems. Enables decoupling between bounded contexts.

### State

**Intent**: Allow an object to alter its behavior when its internal state changes. The object appears to change its class.

**Use when**:
- An object's behavior depends on its state and must change at runtime
- Operations have large multipart conditionals depending on state

**Example**: Order lifecycle (Draft, Submitted, Paid, Shipped, Delivered). Each state is a separate class with state-specific behavior.

### Strategy

**Intent**: Define a family of algorithms, encapsulate each one, and make them interchangeable. The algorithm varies independently from clients that use it.

**Use when**:
- You need different variants of an algorithm
- You want to avoid conditionals for selecting behavior
- Related classes differ only in their behavior

**Architecture relevance**: Core to OCP. Add new strategies without modifying existing code. Used everywhere: payment processing, shipping calculation, pricing rules, notification channels, data validation.

**Example**: `ShippingCalculator` interface with `FlatRateShipping`, `WeightBasedShipping`, `CarrierAPIShipping`. Business logic calls `calculator.calculate(order)` without knowing which strategy.

### Template Method

**Intent**: Define the skeleton of an algorithm in a base class, deferring some steps to subclasses.

**Use when**:
- You want to implement invariant parts of an algorithm once and let subclasses fill in the varying parts
- You want to control which steps subclasses can override

**Difference from Strategy**: Template Method uses inheritance (compile-time). Strategy uses composition (runtime). Prefer Strategy when you need runtime flexibility.

### Visitor

**Intent**: Define a new operation without changing the classes of the elements it operates on.

**Use when**:
- An object structure contains many classes with differing interfaces, and you want to perform operations that depend on their concrete classes
- Many distinct, unrelated operations need to be performed, and you don't want to pollute element classes
- The class hierarchy is stable but operations change frequently

---

## Pattern Selection Guide

**Creating objects**:
- Need families of related objects? → Abstract Factory
- Complex multi-step construction? → Builder
- Defer which class to instantiate? → Factory Method
- Create by copying? → Prototype

**Composing structures**:
- Incompatible interface? → Adapter
- Separate abstraction from implementation? → Bridge
- Tree/hierarchy of objects? → Composite
- Add behavior dynamically? → Decorator
- Simplify complex subsystem? → Facade
- Control access to object? → Proxy

**Managing behavior**:
- Multiple possible handlers? → Chain of Responsibility
- Encapsulate request as object? → Command
- Traverse collection? → Iterator
- Centralize complex interactions? → Mediator
- Notify dependents of changes? → Observer
- Behavior changes with state? → State
- Swap algorithms at runtime? → Strategy
- Skeleton algorithm with variable steps? → Template Method
- Add operations without changing classes? → Visitor
