# The `clone` Plugin

Have you wanted to simply copy the contents of your pipes from one instance to another? Then `plugin:clone` may be right for you!

## What does it do?

Combine one or more pipes together into a single target pipe, complete with `params` support (and works across instances)!

For example, you may have several pipes scattered across your infrastructure in different databases (one on MongoDB here, one on PostgreSQL there, etc.). This plugin allows you to consolidate all of those pipes together in a clean, easy-to-understand way!

## How does it work?

Like the `mrsm copy pipes` command, `plugin:clone` uses `pipe.get_data()` within a `fetch()` function, making it trivial to pass data between instances!

## Ok, I'm hooked. How do I use it?

See `mrsm-compose.yaml` for a complete example. In a nutshell, define the source pipes' keys under `parameters:sources`. No need to specify indices ― those will be pulled automatically from the source pipes.

Consider the snippet below:

```yaml
pipes:
  - connector: "plugin:noaa"
    metric: "weather"
    location: "sc"
    instance: "sql:local"
    columns:
      datetime: "timestamp"
      station: "station"
    parameters:
      stations:
        - "KGMU"
        - "KGGE"
        - "KCEU"

  - connector: "plugin:noaa"
    metric: "weather"
    location: "nc"
    instance: "sql:main"
    columns:
      datetime: "timestamp"
      station: "station"
    parameters:
      stations:
        - "KCLT"
        - "KRDU"
        - "KCPC"

  - connector: "plugin:clone"
    metric: "weather"
    instance: "sql:main"
    parameters:
      sources:
        - pipe:
            connector: "plugin:noaa"
            metric: "weather"
            location: "sc"
            instance: "sql:local"
          backtrack_minutes: 1440
          chunk_minutes: 10080
          params:
            stations:
              - "KGMU"
        - pipe:
            connector: "plugin:noaa"
            metric: "weather"
            location: "nc"
            instance: "sql:main"
            params:
              stations:
                - "_KRDU"
```
In this example, there are two weather pipes: SC and NC. The two pipes are stored separately ― SC's data are stored on `sql:local`, and NC's data are on `sql:main`. The third pipe unions the two tables together into a single table stored on `sql:main`.

Source pipes may be defined in a list under `sources` (example above). You may also define a singoe source pipe under the key `source`.

The following keys control the behavior of the `fetch()`:

- `source:params`  
  The standard Meerschaum params filter dictionary to pass to `source_pipe.get_data()`. Values prefixed with an underscore are negated.

- `source:backtrack_minutes`  
  How many minutes to subtract from the previous sync time. A little bit of overlap (e.g. 1440) is recommended for catching stray rows. Defaults to 1440.

- `source:chunk_minutes`  
  The size of the chunk interval in minutes. If the source pipe uses an integer datetime axis, then this is the number of values. Defaults to 1440.
