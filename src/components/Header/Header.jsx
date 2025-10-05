import React from 'react';
import { FaStethoscope } from 'react-icons/fa';
import './Header.css';

const Header = () => {
  return (
    <header className="app-header">
      <div className="logo-container">
        <div className="logo-icon-wrapper">
          <FaStethoscope size={24} />
        </div>
        <div className="logo-text">
          <h1>OrthoVaidhya Clinic</h1>
          <p>Your Trusted Orthopedic Care Partner</p>
        </div>
      </div>
      {/* The cards on the right are omitted for simplicity as they are faded */}
    </header>
  );
};

export default Header;