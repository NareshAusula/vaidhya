// API configuration and service layer
// Handle environment variables safely

// Safe way to access Vite env vars
const getApiBaseUrl = () => {
  // Check if we're in a Vite environment
  if (typeof import.meta !== 'undefined' && import.meta.env) {
    return import.meta.env.VITE_API_BASE_URL || 'https://orthovaidhya.onrender.com';
  }
  
  // Fallback for production builds
  return 'https://orthovaidhya.onrender.com';
};

const API_BASE_URL = getApiBaseUrl();

console.log('API_BASE_URL:', API_BASE_URL); // Debug log

class ApiService {
  constructor() {
    this.baseURL = API_BASE_URL;
    this.sessionId = this.getOrCreateSessionId();
    console.log('ApiService initialized with baseURL:', this.baseURL); // Debug log
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
    console.log('Making request to:', url); // Debug log
    
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