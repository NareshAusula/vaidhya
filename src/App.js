import React from 'react';
import './App.css';
import Header from './components/Header/Header';
import Chat from './components/Chat/Chat';

function App() {
  return (
    <div className="app-container">
      <Header />
      <main className="main-content">
        <Chat />
      </main>
    </div>
  );
}

export default App;