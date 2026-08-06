import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

/** A white screen tells you nothing. Show the failure on the page. */
class Boundary extends React.Component<
  { children: React.ReactNode },
  { err: Error | null }
> {
  state = { err: null as Error | null }

  static getDerivedStateFromError(err: Error) {
    return { err }
  }

  render() {
    if (this.state.err) {
      return (
        <pre className="crash">
          {this.state.err.message}
          {'\n\n'}
          {this.state.err.stack}
        </pre>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Boundary>
      <App />
    </Boundary>
  </React.StrictMode>,
)
