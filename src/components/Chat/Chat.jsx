import React, { useState, useEffect, useRef } from 'react';
import './Chat.css';
import { FaUserMd, FaSyncAlt, FaPaperPlane, FaSpinner } from 'react-icons/fa';
import ApiService from '../../services/api';

const Chat = () => {
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll to bottom when new messages arrive
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Initialize chat and check connection
  useEffect(() => {
    const initializeChat = async () => {
      try {
        await ApiService.healthCheck();
        setIsConnected(true);
        
        // Add initial welcome message
        const welcomeMessage = {
          id: Date.now(),
          text: "👋 Hi, I am Doctor's Assistant for OrthoVaidhya Clinic. What is your name?",
          sender: 'bot',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          type: 'message',
          buttons: []
        };
        setMessages([welcomeMessage]);
      } catch (error) {
        console.error('Failed to connect to API:', error);
        setIsConnected(false);
        
        // Show connection error message
        const errorMessage = {
          id: Date.now(),
          text: "❌ Unable to connect to the medical assistant. Please check your connection and try again.",
          sender: 'system',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          type: 'error',
          buttons: []
        };
        setMessages([errorMessage]);
      }
    };

    initializeChat();
  }, []);

  // Handle sending messages
  const handleSendMessage = async (messageText = null) => {
    const textToSend = messageText || inputMessage.trim();
    if (!textToSend || isLoading) return;

    // Add user message to chat
    const userMessage = {
      id: Date.now(),
      text: textToSend,
      sender: 'user',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      type: 'message',
      buttons: []
    };

    setMessages(prev => [...prev, userMessage]);
    setInputMessage('');
    setIsLoading(true);

    try {
      // Send message to API
      const response = await ApiService.sendMessage(textToSend);
      
      if (response.status === 'success' && response.response) {
        // Add bot response to chat
        const botMessage = {
          id: Date.now() + 1,
          text: response.response.text,
          sender: 'bot',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          type: response.response.type || 'message',
          buttons: response.response.buttons || []
        };
        
        setMessages(prev => [...prev, botMessage]);
      } else {
        throw new Error('Invalid response from server');
      }
    } catch (error) {
      console.error('Error sending message:', error);
      
      // Add error message
      const errorMessage = {
        id: Date.now() + 1,
        text: "❌ Sorry, I'm having trouble processing your message. Please try again.",
        sender: 'system',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        type: 'error',
        buttons: []
      };
      
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle button clicks
  const handleButtonClick = (buttonValue) => {
    handleSendMessage(buttonValue);
  };

  // Handle reset/refresh
  const handleReset = async () => {
    try {
      setIsLoading(true);
      await ApiService.resetSession();
      
      // Clear messages and show welcome message
      const welcomeMessage = {
        id: Date.now(),
        text: "👋 Hi, I am Doctor's Assistant for OrthoVaidhya Clinic. What is your name?",
        sender: 'bot',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        type: 'message',
        buttons: []
      };
      
      setMessages([welcomeMessage]);
    } catch (error) {
      console.error('Error resetting session:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle Enter key press
  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // Render message component
  const renderMessage = (message) => {
    const messageClass = `message ${
      message.sender === 'user' ? 'user-message' : 
      message.sender === 'system' ? 'system-message' : 'assistant-message'
    }`;

    return (
      <div key={message.id} className={messageClass}>
        <div className="message-content">
          <p dangerouslySetInnerHTML={{ __html: message.text.replace(/\n/g, '<br>') }} />
          
          {/* Render buttons if present */}
          {message.buttons && message.buttons.length > 0 && (
            <div className="message-buttons">
              {message.buttons.map((button, index) => (
                <button
                  key={index}
                  className="message-button"
                  onClick={() => handleButtonClick(button.value)}
                  disabled={isLoading}
                >
                  {button.text}
                </button>
              ))}
            </div>
          )}
        </div>
        <span className="message-timestamp">{message.timestamp}</span>
      </div>
    );
  };

  return (
    <div className="chat-container">
      <div className="chat-header">
        <div className="chat-header-left">
          <div className="chat-icon-wrapper">
            <FaUserMd size={20} />
          </div>
          <div className="chat-title">
            <h2>OrthoVaidhya Assistant</h2>
            <div className="status">
              <span className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`}></span>
              {isConnected ? 'Connected' : 'Disconnected'}
            </div>
          </div>
        </div>
        <div className="chat-header-right">
          <FaSyncAlt 
            className={`refresh-icon ${isLoading ? 'spinning' : ''}`} 
            size={16} 
            onClick={handleReset}
            title="Reset conversation"
          />
        </div>
      </div>

      <div className="chat-messages">
        {messages.map(renderMessage)}
        {isLoading && (
          <div className="message assistant-message loading">
            <div className="message-content">
              <FaSpinner className="spinner" size={16} />
              <span>Assistant is typing...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        <input 
          ref={inputRef}
          type="text" 
          value={inputMessage}
          onChange={(e) => setInputMessage(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Type your message..." 
          disabled={isLoading || !isConnected}
        />
        <button 
          className="send-button"
          onClick={() => handleSendMessage()}
          disabled={isLoading || !inputMessage.trim() || !isConnected}
        >
          {isLoading ? <FaSpinner className="spinner" size={16} /> : <FaPaperPlane size={16} />}
        </button>
      </div>

      <div className="disclaimer">
        <strong>Important:</strong> This assistant provides general medical information and is not a substitute for professional medical advice. In case of emergency, please call your local emergency number immediately.
      </div>
    </div>
  );
};

export default Chat;