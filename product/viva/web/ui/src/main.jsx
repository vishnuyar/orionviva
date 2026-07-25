import {StrictMode} from 'react'
import {createRoot} from 'react-dom/client'
import App from './App'
import './app.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <div className="wrap">
      <header>
        <h1>Viva</h1>
        <span className="sub">your money, held honestly</span>
      </header>
      <App />
    </div>
  </StrictMode>
)
