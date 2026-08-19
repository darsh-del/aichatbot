# SMTP Alerts (Out of Credits Notifications)

The chatbot is configured to automatically alert you via email if the underlying LLM provider (e.g., Anthropic, OpenAI) runs out of credits or blocks the request. 

This is triggered when the backend catches an API exception containing keywords like `404`, `402`, or `credit`.

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

If you have zero credits and multiple users are interacting with the chatbot simultaneously, the API will fail repeatedly. To prevent your inbox from being flooded, the `app/notifier.py` script features a **1-hour debounce timer**.

- When the first error occurs, an email is sent immediately.
- For the next 3600 seconds (1 hour), any subsequent errors are silently logged and ignored.
- After 1 hour, the lock resets, and the next error will trigger a new email.

## 🧪 How to Test

You can manually test this by temporarily changing your `ANTHROPIC_API_KEY` to an invalid key (e.g., `sk-ant-invalid-key`) in your local `.env` file and attempting to send a message to the chatbot. Check the backend logs to see the SMTP trigger!
