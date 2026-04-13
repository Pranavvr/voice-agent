import React, { useEffect, useRef } from 'react';

const AudioVisualizer = ({ isActive, color = '#7c3aed' }) => {
  const canvasRef = useRef(null);
  const animationRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    let phase = 0;

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      
      const width = canvas.width;
      const height = canvas.height;
      const centerY = height / 2;
      
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.lineCap = 'round';
      
      // Draw multiple waves for a "rich" effect
      for (let j = 0; j < 3; j++) {
        const opacity = 1 - (j * 0.3);
        ctx.strokeStyle = `${color}${Math.floor(opacity * 255).toString(16).padStart(2, '0')}`;
        ctx.beginPath();
        
        for (let x = 0; x < width; x++) {
          const amplitude = isActive ? (30 + j * 10) : 5;
          const frequency = isActive ? 0.02 : 0.01;
          const y = centerY + Math.sin(x * frequency + phase + (j * 2)) * amplitude;
          
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      phase += isActive ? 0.15 : 0.05;
      animationRef.current = requestAnimationFrame(draw);
    };

    draw();

    return () => cancelAnimationFrame(animationRef.current);
  }, [isActive, color]);

  return (
    <canvas 
      ref={canvasRef} 
      width={600} 
      height={200} 
      className="w-full h-48 opacity-80"
    />
  );
};

export default AudioVisualizer;
