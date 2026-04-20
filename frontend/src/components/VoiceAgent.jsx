import React, { useState } from 'react';
import { useVoiceAgent } from '../hooks/useVoiceAgent';
import AudioVisualizer from './AudioVisualizer';

const VoiceAgent = () => {
  const [userName, setUserName] = useState('');
  const userId = userName ? `user_${userName.toLowerCase().replace(/\s+/g, '_')}` : 'guest';

  const {
    isConnected,
    isRecording,
    transcript,
    connect,
    disconnect,
    startRecording,
    stopRecording
  } = useVoiceAgent(userId, userName || 'User');

  const handleToggleConnection = () => {
    if (isConnected) {
      disconnect();
    } else {
      connect();
    }
  };

  const handleToggleMic = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="glass-card w-full max-w-2xl overflow-hidden flex flex-col items-center">
        {/* Header */}
        <div className="w-full p-8 text-center border-b border-white/5">
          <h1 className="text-4xl font-bold gradient-text mb-2">Voice Agent</h1>
          <p className="text-zinc-500 text-sm">
            {isConnected ? 'Session Active' : 'Ready to Start'}
          </p>
        </div>

        {/* Visualizer Area */}
        <div className="flex-1 w-full flex flex-col items-center justify-center p-12 space-y-8">
          <div className={`relative ${isRecording ? 'animate-pulse-glow' : ''}`}>
             <AudioVisualizer isActive={isRecording} />
             {!isConnected && (
               <div className="absolute inset-0 flex items-center justify-center">
                 <div className="w-20 h-20 bg-violet-600/20 rounded-full blur-2xl" />
               </div>
             )}
          </div>
          
          <div className="text-center max-w-md h-12">
            <p className="text-zinc-400 italic">
              {transcript || (isRecording ? "Listening..." : "Click start to begin")}
            </p>
          </div>
        </div>

        {/* Footer / Controls */}
        <div className="w-full p-8 bg-white/5 flex flex-col items-center gap-4">
          {!isConnected && (
            <input
              type="text"
              placeholder="Enter your name"
              value={userName}
              onChange={(e) => setUserName(e.target.value)}
              className="bg-zinc-800 text-white text-sm rounded-lg px-4 py-2 outline-none border border-white/10 focus:border-violet-500 w-56 text-center"
            />
          )}
          <div className="flex gap-4">
          <button
            onClick={handleToggleConnection}
            className={`btn-primary ${isConnected ? 'bg-zinc-800' : ''}`}
          >
            {isConnected ? 'Disconnect' : 'Connect Agent'}
          </button>
          
          <button 
            onClick={handleToggleMic}
            disabled={!isConnected}
            className={`btn-primary ${isRecording ? 'bg-red-500 shadow-red-500/50' : ''} ${!isConnected ? 'opacity-30 cursor-not-allowed' : ''}`}
          >
            {isRecording ? 'Stop Recording' : 'Start Mic'}
          </button>
          </div>
        </div>
      </div>
      
      {/* Background Glow */}
      <div className="fixed -bottom-40 -left-40 w-96 h-96 bg-violet-600/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="fixed -top-40 -right-40 w-96 h-96 bg-blue-600/10 rounded-full blur-[120px] pointer-events-none" />
    </div>
  );
};

export default VoiceAgent;
