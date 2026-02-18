# LangGraph Service - Aarogya Assistant (AA)

Intelligent chatbot service for healthcare appointment booking using graph-based conversation flow.

## Architecture

```
langGraph_service/
├── schemas/          # Data models and state definitions
│   ├── state.py      # Conversation state structure
│   └── models.py     # Pydantic models for requests/responses
├── tools/            # Utility functions
│   ├── datetime_tools.py      # IST timezone, date parsing
│   ├── appointment_tools.py   # Appointment booking operations
│   ├── doctor_tools.py        # Doctor search and discovery
│   └── profile_tools.py       # Patient profile management
├── nodes/            # Processing nodes
│   ├── classifier_node.py     # Intent classification
│   ├── appointment_node.py    # Appointment handling
│   ├── doctor_node.py         # Doctor search handling
│   ├── profile_node.py        # Profile update handling
│   └── response_node.py       # Greetings and out-of-scope
├── memory.py         # Conversation history management
└── graph.py          # Main orchestrator
```

## Features

### 1. Appointment Booking
- **Today requests**: Explains 24-hour advance booking rule, suggests tomorrow
- **Tomorrow/future dates**: Shows available slots with validation
- **Time preferences**: Finds slots near requested time (e.g., "10:30 AM")
- **One appointment per day**: Validates before showing slots
- **Auto-request**: Books appointments via `/appointments/bot/request`

### 2. Doctor Search
- **By specialization**: "Find cardiologist"
- **By name**: "Dr. Smith"
- **Nearby**: "Doctors near me" (location-based)
- **List specialities**: Shows all available specializations

### 3. Profile Management
- **View profile**: Shows name, DOB, age, email
- **Update name**: "Update my name to John Doe"
- **Update DOB**: "Change my DOB to 1990-05-15"

### 4. Edge Cases Handled
- **Past dates**: Rejects with appropriate message
- **Within 24 hours**: Explains booking window
- **Random day names**: Asks for specific date
- **Time only**: Asks for date
- **Out of scope**: Redirects to supported features

## Conversation Flow

```
User Message
    ↓
Classify Intent (classifier_node)
    ↓
Route to Handler:
    ├── Greeting → response_node
    ├── Appointment → appointment_node
    ├── Doctor Search → doctor_node
    ├── Profile → profile_node
    └── Out of Scope → response_node
    ↓
Generate Response
    ↓
Store in Memory
    ↓
Return to User
```

## Memory Management

- **Storage**: In-memory (production: Redis/SQLite)
- **Thread ID**: `user_id` (supports parallel users)
- **Window**: Last 50 messages per user
- **TTL**: 24 hours of inactivity
- **Clear on logout**: Call `/chat/clear-context`

## Date/Time Handling

All dates and times use **IST (Asia/Kolkata)** timezone.

### Supported Date Formats
- Relative: "today", "tomorrow", "day after tomorrow"
- ISO: "2024-12-25"
- Friendly: "25 December 2024", "Dec 25, 2024"
- Slash: "25/12/2024"

### Supported Time Formats
- 24-hour: "14:30"
- 12-hour: "2:30 PM", "2 PM"

### Booking Rules
- **24-hour advance**: Appointments must be ≥24 hours from now
- **One per day**: Patient can only have one appointment per day
- **Doctor approval**: 24 hours for doctor to approve
- **Payment window**: 15 minutes after approval

## API Integration

### Chat Endpoint
```python
POST /chat
{
    "message": "Show me cardiologist slots for tomorrow",
    "conversation_id": "conv_123"  # Optional
}

Response:
{
    "response": "✅ Found 5 available slots...",
    "conversation_id": "conv_123",
    "suggestions": ["Book first slot", "Try another doctor"]
}
```

### Clear Context
```python
POST /chat/clear-context
# Clears conversation history for current user
```

### Get Specialities
```python
GET /doctors/specialities/list
# Returns list of unique doctor specializations
```

## Usage Example

```python
from langGraph_service.graph import process_message, clear_user_context

# Process message
result = await process_message(
    user_id=123,
    patient_id=456,
    patient_name="John Doe",
    message="Show me cardiologist slots for tomorrow",
    db=db_session
)

print(result["response"])
print(result["suggestions"])

# Clear context on logout
clear_user_context(user_id=123)
```

## Testing Scenarios

### 1. Today Request
```
User: "Show me slots for today"
Bot: "📅 Current IST Time: 18 Feb 2026, 02:30 PM
     ⚠️ Appointments must be booked at least 24 hours in advance.
     ✅ You can book from 19 February 2026 onwards."
```

### 2. Tomorrow with Speciality
```
User: "Find cardiologist slots for tomorrow"
Bot: "👨‍⚕️ Found 3 cardiologist doctors:
     1. Dr. Smith - ₹500
     2. Dr. Jones - ₹600
     Which doctor would you like?"
```

### 3. Time Preference
```
User: "Show slots for tomorrow at 10:30 AM"
Bot: "✅ Found 3 slots near 10:30 AM:
     1. 10:00 AM - 10:30 AM
     2. 10:30 AM - 11:00 AM
     3. 11:00 AM - 11:30 AM"
```

### 4. Profile Update
```
User: "Update my name to Jane Doe"
Bot: "✅ Your name has been updated to: Jane Doe"
```

### 5. Out of Scope
```
User: "What's the weather today?"
Bot: "I'm specialized in healthcare appointments. 🏥
     I can help with finding doctors and booking appointments."
```

## Future Enhancements

1. **LLM Integration**: Replace rule-based classification with GPT/Claude
2. **Persistent Storage**: Move from in-memory to Redis/PostgreSQL
3. **Multi-language**: Support Hindi, regional languages
4. **Voice Input**: Speech-to-text integration
5. **Appointment Reminders**: Proactive notifications
6. **Medical History**: Context-aware recommendations
7. **Prescription Management**: Upload and track prescriptions
8. **Lab Reports**: Integration with diagnostic centers

## Dependencies

- FastAPI
- SQLAlchemy
- Pydantic
- Python 3.10+
- zoneinfo (for IST timezone)

## Notes

- All database operations are async-compatible
- Memory is thread-safe for concurrent users
- Date parsing handles multiple formats gracefully
- Error handling with fallback responses
- Logging for debugging and monitoring
