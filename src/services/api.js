// API configuration and service layer
// Prefer env var; fallback to backend default port 5000

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:5001';

class ApiService {
  constructor() {
    this.baseURL = API_BASE_URL;
    this.sessionId = this.getOrCreateSessionId();
  }

  // Generate or retrieve session ID
  getOrCreateSessionId() {
    let sessionId = localStorage.getItem('chat_session_id');
    if (!sessionId) {
      sessionId = 'session_' + Math.random().toString(36).substring(7) + '_' + Date.now();
      localStorage.setItem('chat_session_id', sessionId);
    }
    return sessionId;
  }

  // Generic API request method
  async makeRequest(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const defaultOptions = {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    };

    const config = { ...defaultOptions, ...options };

    try {
      const response = await fetch(url, config);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      return data;
    } catch (error) {
      console.error('API request failed:', error);
      throw error;
    }
  }

  // Send message to chat API
  async sendMessage(message) {
    return this.makeRequest('/api/chat', {
      method: 'POST',
      body: JSON.stringify({
        message: message,
        session_id: this.sessionId
      })
    });
  }

  // Reset chat session
  async resetSession() {
    const response = await this.makeRequest('/api/reset', {
      method: 'POST',
      body: JSON.stringify({
        session_id: this.sessionId
      })
    });
    
    // Generate new session ID after reset
    this.sessionId = this.getOrCreateSessionId();
    return response;
  }

  // Health check
  async healthCheck() {
    return this.makeRequest('/health');
  }

  // Get current session ID
  getCurrentSessionId() {
    return this.sessionId;
  }
}

// Export singleton instance
export default new ApiService();