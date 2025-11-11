# ZanderMCP Advanced FastMCP Features

This document describes the advanced FastMCP features implemented in ZanderMCP server.

## Overview

The server now uses sophisticated FastMCP capabilities beyond basic tools:

1. **Tags** - Tool categorization and filtering
2. **Resources** - Read-only data access
3. **Prompts** - AI workflow templates

## Tags-Based Organization

### Tool Categories

All 14 tools are tagged for easy filtering and organization:

#### Real-time Monitoring (`realtime`, `monitoring`, `production`)
- `get_current_cognitive_load()` - Latest workload prediction
- `get_cognitive_state()` - Interpreted cognitive state
- `get_workload_trend()` - Trend analysis (also tagged `analysis`)

#### Historical Queries (`historical`, `database`, `production`)
- `query_workload_history()` - Historical predictions
- `get_session_summary()` - Session statistics (also `session`)
- `analyze_cognitive_patterns()` - Pattern analysis (also `analysis`, `research`)
- `get_recent_events()` - Recent annotations (also `research`, `annotation`)

#### Session Management (`session`, `management`/`monitoring`, `production`)
- `get_active_sessions()` - List active sessions
- `end_session()` - Close a session

#### Research Tools (`research`, `annotation`, `production`)
- `annotate_event()` - Mark significant moments

#### Admin Tools (`admin`, `monitoring`/`classifier`, `debug`/`production`)
- `get_buffer_status()` - Buffer statistics
- `list_classifiers()` - Available classifiers
- `get_server_stats()` - Server statistics

### Using Tags for Filtering

You can filter tools when creating the server:

```python
# Production deployment - hide debug tools
mcp_prod = FastMCP(
    name="ZanderMCP-Production",
    include_tags={"production"},
    exclude_tags={"debug"}
)

# Development deployment - show everything
mcp_dev = FastMCP(
    name="ZanderMCP-Dev",
    # No filtering
)

# Research-only server
mcp_research = FastMCP(
    name="ZanderMCP-Research",
    include_tags={"research", "historical", "annotation"}
)

# Real-time monitoring only
mcp_monitor = FastMCP(
    name="ZanderMCP-Monitor",
    include_tags={"realtime", "monitoring"}
)
```

### Tag Hierarchy

Tags are organized by:

1. **Use Case**: `production`, `development`, `research`
2. **Data Source**: `realtime`, `historical`, `database`
3. **Function**: `monitoring`, `analysis`, `annotation`, `management`
4. **Access Level**: `admin`, `debug`
5. **Domain**: `session`, `classifier`

## Resources (4 Total)

Resources provide read-only data access, separate from tool execution.

### 1. Server Configuration (`config://server`)

**Tags:** `config`, `admin`

Returns server configuration including:
- Server metadata (name, version, environment)
- WebSocket settings
- Database configuration
- Classifier information
- Signal processing parameters

**Usage:**
```python
# AI Assistant reads configuration
config = await client.read_resource("config://server")
```

**Example Output:**
```json
{
  "server": {
    "name": "ZanderMCP",
    "version": "1.0.0",
    "environment": "production"
  },
  "websocket": {
    "host": "0.0.0.0",
    "port": 8765,
    "max_connections": 10
  },
  "classifiers": {
    "default": "signal_processing",
    "available": ["signal_processing"]
  }
}
```

### 2. Classifiers Configuration (`config://classifiers`)

**Tags:** `config`, `classifier`

Returns detailed classifier metadata:
- Classifier type (deterministic, ML, etc.)
- Version information
- Description
- Configuration parameters

**Example Output:**
```json
{
  "classifiers": {
    "signal_processing": {
      "type": "deterministic",
      "version": "1.0.0",
      "description": "Signal processing based workload classifier",
      "parameters": {...}
    }
  },
  "default": "signal_processing",
  "count": 1
}
```

### 3. Session Data Export (`data://session/{session_id}/export`)

**Tags:** `data`, `export`, `research`

Exports complete session data as CSV format.

**URI Template:** Uses `{session_id}` parameter

**Usage:**
```python
# Export session data
csv_data = await client.read_resource("data://session/abc-123/export")
```

**Output Format:**
```csv
timestamp,workload,confidence,classifier,session_id,user_id
2025-01-10T14:20:00Z,0.65,0.89,signal_processing,abc-123,user_1
2025-01-10T14:20:01Z,0.67,0.91,signal_processing,abc-123,user_1
...
```

### 4. API Documentation (`docs://api-guide`)

**Tags:** `docs`, `help`

Returns comprehensive API guide as markdown text:
- Tool categories and usage
- Available resources
- Example workflows
- Best practices

**Usage:**
```python
# Get API documentation
docs = await client.read_resource("docs://api-guide")
```

## Prompts (4 Total)

Prompts provide structured workflow templates for AI assistants.

### 1. Comprehensive Cognitive Load Analysis

**Function:** `analyze_cognitive_load(user_id: Optional[str] = None)`
**Tags:** `analysis`, `monitoring`

Guides AI through a complete cognitive load analysis:
1. Current state assessment
2. Trend analysis over 30 minutes
3. Recommendations based on state
4. Summary of findings

**Usage:**
```python
# AI gets prompt template
prompt = await client.get_prompt("analyze_cognitive_load", {"user_id": "user_1"})
# AI follows the structured workflow in the prompt
```

### 2. Research Session Analysis

**Function:** `research_session_analysis(session_id: str)`
**Tags:** `research`, `analysis`

Guides AI through detailed research analysis:
1. Session overview and statistics
2. Pattern analysis (high/low load periods)
3. Event correlation with workload
4. Data export for offline analysis
5. Research insights and hypotheses

### 3. Monitor Active Sessions

**Function:** `monitor_active_sessions()`
**Tags:** `monitoring`, `production`

Guides AI through operational monitoring:
1. Review all active sessions
2. System health checks
3. Real-time cognitive load monitoring
4. Alert identification
5. Summary dashboard generation

### 4. Getting Started Guide

**Function:** `getting_started_guide()`
**Tags:** `onboarding`, `help`

Guides AI through onboarding new users:
1. Initial setup verification
2. First cognitive load check
3. Understanding trends
4. Annotation demonstration
5. Available capabilities overview
6. Next steps and tips

## Tools vs Resources: When to Use Each

### Use Tools When:
- ✅ Executing an action or computation
- ✅ Querying with complex parameters
- ✅ Operations that modify state (annotations, session management)
- ✅ Real-time data requiring current context

**Examples:**
- `get_current_cognitive_load()` - Requires real-time computation
- `annotate_event()` - Modifies database state
- `analyze_cognitive_patterns()` - Complex query with date ranges

### Use Resources When:
- ✅ Reading static or semi-static configuration
- ✅ Accessing reference documentation
- ✅ Exporting data for external use
- ✅ Read-only operations with simple parameters

**Examples:**
- `config://server` - Configuration is mostly static
- `docs://api-guide` - Documentation is static
- `data://session/{id}/export` - Data export for offline use

## Tag Filtering Use Cases

### Development vs Production

```python
# Production: Hide debug tools
mcp_prod = FastMCP(
    name="ZanderMCP",
    exclude_tags={"debug"}  # Hide get_buffer_status, get_server_stats
)

# Development: Show everything
mcp_dev = FastMCP(
    name="ZanderMCP-Dev"
    # No filtering
)
```

### Role-Based Access

```python
# End users: Only production tools
user_server = FastMCP(
    name="ZanderMCP-User",
    include_tags={"production", "monitoring", "realtime"}
)

# Researchers: Historical and research tools
research_server = FastMCP(
    name="ZanderMCP-Research",
    include_tags={"research", "historical", "annotation"}
)

# Admins: Everything including debug
admin_server = FastMCP(
    name="ZanderMCP-Admin"
    # No filtering
)
```

### Feature Flags

```python
# Gradually roll out new classifier
if FEATURE_ML_CLASSIFIER:
    @mcp.tool(tags={"experimental", "classifier"})
    async def use_ml_classifier():
        ...

# Production excludes experimental
mcp_prod = FastMCP(exclude_tags={"experimental"})
```

## Advanced Patterns

### Resource Templates

Resources support URI templates with parameters:

```python
@mcp.resource("data://session/{session_id}/export")
async def export_session_data(session_id: str) -> str:
    # Parameter automatically extracted from URI
    return csv_data
```

### Context in Resources

Resources can use Context API like tools:

```python
@mcp.resource("config://server")
async def server_config(ctx: Context = None) -> dict:
    if ctx:
        await ctx.info("Reading server configuration")
    # Access app context, log operations, etc.
```

### Dynamic Prompts

Prompts can accept parameters for personalization:

```python
@mcp.prompt
def analyze_cognitive_load(user_id: Optional[str] = None) -> str:
    user_filter = f" for user {user_id}" if user_id else ""
    return f"""Perform analysis{user_filter}:
    1. Call get_current_cognitive_load({f"user_id='{user_id}'" if user_id else ""})
    ...
    """
```

## Benefits of These Features

### 1. Tags Enable:
- ✅ Environment-specific deployments (dev/prod)
- ✅ Role-based tool access
- ✅ Feature flags for gradual rollouts
- ✅ Easier tool discovery and organization

### 2. Resources Enable:
- ✅ Separation of data from actions
- ✅ Better caching (resources are immutable)
- ✅ Self-documenting APIs
- ✅ Standard data export workflows

### 3. Prompts Enable:
- ✅ Consistent AI workflows
- ✅ Best practices guidance
- ✅ Faster onboarding
- ✅ Complex multi-step operations made simple

## Future Enhancements

### Potential Additions:

1. **More Granular Tags**
   - `{low-latency}` vs `{high-latency}`
   - `{experimental}` for beta features
   - `{requires-auth}` for authenticated tools

2. **Additional Resources**
   - `data://classifier/{name}/metadata` - Per-classifier details
   - `data://user/{user_id}/history` - User workload history
   - `config://channels` - EEG channel configuration

3. **More Prompts**
   - `compare_classifiers()` - Compare classifier performance
   - `optimize_session_settings()` - Tune configuration
   - `troubleshoot_connection()` - Debug connectivity issues

4. **Server Composition** (when needed)
   - Separate classifier service
   - Dedicated model training service
   - Multi-tenant architecture

## References

- FastMCP Tags Documentation: https://gofastmcp.com/servers/server#tag-based-filtering
- FastMCP Resources: https://gofastmcp.com/servers/resources
- FastMCP Prompts: https://gofastmcp.com/servers/prompts
- Server Composition: https://gofastmcp.com/servers/composition
