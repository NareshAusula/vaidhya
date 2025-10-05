# Medical Bot - Environment Setup

## 🔐 Securing Your API Keys

This bot uses environment variables to keep your API keys secure and out of the source code.

### Setup Instructions

1. **Copy the example environment file:**
   ```bash
   cp .env.example .env
   ```

2. **Edit the `.env` file with your actual API keys:**
   ```bash
   # Open .env in your text editor and replace the placeholder values
   GEMINI_API_KEY=your_actual_gemini_api_key_here
   MicrosoftAppId=your_microsoft_app_id_if_needed
   MicrosoftAppPassword=your_microsoft_app_password_if_needed
   ```

3. **Get your Gemini API Key:**
   - Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
   - Create a new API key
   - Copy it to your `.env` file

### 🔒 Security Best Practices

- ✅ **DO**: Keep your `.env` file in `.gitignore`
- ✅ **DO**: Use environment variables for all sensitive data
- ✅ **DO**: Share `.env.example` (without real keys) with your team
- ❌ **DON'T**: Commit `.env` files to version control
- ❌ **DON'T**: Hardcode API keys in source code
- ❌ **DON'T**: Share your `.env` file publicly

### 📁 File Structure
```
medical_bot/
├── .env                 # Your actual environment variables (keep secret!)
├── .env.example         # Template for environment variables (safe to share)
├── .gitignore          # Prevents .env from being committed
├── medical_qna.py      # Main bot code (now uses environment variables)
└── requirements.txt    # Updated with python-dotenv
```

### 🚀 Running the Bot

After setting up your `.env` file:

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python medical_qna.py
```

The bot will automatically load your environment variables from the `.env` file.

### ❗ Troubleshooting

If you get "GEMINI_API_KEY environment variable is required but not set":

1. Make sure your `.env` file exists in the project directory
2. Check that `GEMINI_API_KEY=your_key_here` is in the `.env` file (no quotes needed)
3. Restart your application after making changes to `.env`

### 🔄 For Production Deployment

In production environments (Heroku, AWS, Azure, etc.), set environment variables through the platform's configuration system rather than using a `.env` file:

- **Heroku**: Use `heroku config:set GEMINI_API_KEY=your_key`
- **Azure**: Set in App Service Configuration
- **AWS**: Use Systems Manager Parameter Store or Environment Variables