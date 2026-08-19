# Infrastructure Alerting (SMTP)

The chatbot acts as its own SRE (Site Reliability Engineer) and is configured to automatically alert you via email if any critical piece of the infrastructure fails.

## 🚨 Alert Categories

The system actively monitors and alerts on the following 6 failure points:

1. **LLM Out of Credits (402/404)** - Upstream provider billing issue.
2. **LLM Rate Limits (429)** - Traffic spikes exceeding provider quotas.
3. **LLM Provider Outage (500+)** - Upstream provider servers are down.
4. **Redis Database Down** - Breaks session memory and tool caching.
5. **Weaviate Database Down** - Breaks RAG (Knowledge Base) retrieval.
6. **External Tool Failure (MCP)** - External APIs (like booking systems) failing.

## ⚙️ Environment Variables Required

To enable this feature, you must add the following variables to your GitHub Secrets (or your local `.env` file). If these are missing, the backend will safely skip sending the email and log a warning instead.

```env
# The address of your SMTP server (e.g., smtp.gmail.com)
SMTP_SERVER=smtp.gmail.com

# The SMTP port (usually 587 for TLS)
SMTP_PORT=587

# The email address you are sending FROM (must be authenticated)
SMTP_USER=your-bot-email@gmail.com

# The app password or SMTP password for the user above
SMTP_PASS=your-secure-app-password

# The email address you want to receive the alerts TO (e.g., your personal/admin email)
SMTP_TO=admin@bucketlistt.com
```

## 🛡️ Anti-Spam Safety (Debouncing)

To prevent your inbox from being flooded if a service goes down during high traffic, the `app/notifier.py` script features dynamic **debounce timers** for each specific type of error:

- **15 Minutes:** Redis Down, Weaviate Down
- **30 Minutes:** Rate Limits, LLM Outages, MCP Tool Errors
- **1 Hour:** Out of Credits

For example, if Redis crashes, you will get exactly one email immediately. For the next 15 minutes, any subsequent Redis errors are silently logged. After 15 minutes, the lock resets.

## 🧪 How to Test

You can manually test this by temporarily changing your `ANTHROPIC_API_KEY` to an invalid key (e.g., `sk-ant-invalid-key`) in your local `.env` file and attempting to send a message to the chatbot. Check the backend logs to see the SMTP trigger!
