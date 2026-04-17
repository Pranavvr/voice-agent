import { useState, useEffect, useRef, useCallback } from 'react';

const WS_URL = 'ws://localhost:8000/ws/chat';

export const useVoiceAgent = (userId = 'user_123', userName = 'Pranav') => {
  const [isConnected, setIsConnected] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState('');
  
  const wsRef = useRef(null);
  const audioContextRef = useRef(null);
  const processorRef = useRef(null);
  const sourceRef = useRef(null);
  const nextPlaybackTimeRef = useRef(0);

  const connect = useCallback(() => {
    const ws = new WebSocket(`${WS_URL}?user_id=${userId}&name=${userName}`);
    
    ws.onopen = () => {
      console.log('Connected to Voice Backend');
      setIsConnected(true);
    };

    ws.onmessage = async (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'response.created') {
        setTranscript('');
      }

      if (data.type === 'response.audio_transcript.delta') {
        // Sync text appearance with the audio playback queue
        let delay = 0;
        if (audioContextRef.current) {
           delay = Math.max(0, nextPlaybackTimeRef.current - audioContextRef.current.currentTime);
        }
        setTimeout(() => {
          setTranscript(prev => prev + data.delta);
        }, delay * 1000);
      }
      
      if (data.type === 'response.audio.delta') {
        playAudioDelta(data.delta);
      }
    };

    ws.onclose = () => {
      console.log('Disconnected from Voice Backend');
      setIsConnected(false);
      stopRecording();
    };

    wsRef.current = ws;
  }, [userId, userName]);

  const playAudioDelta = (base64Audio) => {
    if (!audioContextRef.current) {
        audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
        nextPlaybackTimeRef.current = audioContextRef.current.currentTime;
    }
    
    // Resume context if suspended (browser behavior)
    if (audioContextRef.current.state === 'suspended') {
        audioContextRef.current.resume();
    }

    const binary = atob(base64Audio);
    const len = binary.length;
    const bytes = new Int16Array(len / 2);
    for (let i = 0; i < len; i += 2) {
      bytes[i / 2] = (binary.charCodeAt(i + 1) << 8) | binary.charCodeAt(i);
    }
    
    const float32 = new Float32Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) {
      float32[i] = bytes[i] / 32768;
    }

    const buffer = audioContextRef.current.createBuffer(1, float32.length, 24000);
    buffer.getChannelData(0).set(float32);
    
    const source = audioContextRef.current.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContextRef.current.destination);

    // Schedule playback
    const startTime = Math.max(nextPlaybackTimeRef.current, audioContextRef.current.currentTime);
    source.start(startTime);
    
    // Update next playback time (duration = length / sampleRate)
    nextPlaybackTimeRef.current = startTime + buffer.duration;
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
      sourceRef.current = audioContextRef.current.createMediaStreamSource(stream);
      
      // Simple processor for demo purposes
      // In production, AudioWorklet is preferred
      processorRef.current = audioContextRef.current.createScriptProcessor(4096, 1, 1);
      
      processorRef.current.onaudioprocess = (e) => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          const inputData = e.inputBuffer.getChannelData(0);
          const pcmData = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i++) {
            pcmData[i] = Math.max(-1, Math.min(1, inputData[i])) * 0x7FFF;
          }
          
          const base64 = btoa(String.fromCharCode(...new Uint8Array(pcmData.buffer)));
          wsRef.current.send(JSON.stringify({
            type: 'input_audio_buffer.append',
            audio: base64
          }));
        }
      };

      sourceRef.current.connect(processorRef.current);
      processorRef.current.connect(audioContextRef.current.destination);
      setIsRecording(true);
    } catch (err) {
      console.error('Error accessing microphone:', err);
    }
  };

  const stopRecording = () => {
    if (processorRef.current) {
      processorRef.current.disconnect();
      sourceRef.current.disconnect();
    }
    setIsRecording(false);
  };

  const disconnect = () => {
    if (wsRef.current) {
      wsRef.current.close();
    }
  };

  return { isConnected, isRecording, transcript, connect, disconnect, startRecording, stopRecording };
};
