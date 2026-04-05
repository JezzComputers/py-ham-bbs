import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'

class RadioSocket {
  private websocket: WebSocket = null!;
  constructor(private _url: string) {}


  connect<DataType extends Object>(onMessage: (message: DataType) => void, onError: (error: any) => void) {
    this.websocket = new WebSocket(this._url);

    this.websocket.onmessage = (event) => {
      if(typeof event.data === "string") {
        try {
          const data = JSON.parse(event.data);
          onMessage(data as DataType);
        } catch (e) {
          console.error("Failed to parse message as JSON:", e);
        }
      }
    }

    this.websocket.onerror = (error) => {
      console.error("WebSocket error:", error);
      onError(error);
    }
  }
  
  public sendMessage(message: string) {
    if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
      this.websocket.send(message);
    } else {
      console.error("WebSocket is not open. Unable to send message.");
    }
  }


}

const radioSocket = new RadioSocket("ws://localhost:8765");
radioSocket.connect((data: string) => {
  console.log("Received message:", data);
}, (error: any) => {
  console.error("WebSocket error:", error);
});

// createRoot(document.getElementById('root')!).render(
//   <StrictMode>
//     <App />
//   </StrictMode>,
// )
