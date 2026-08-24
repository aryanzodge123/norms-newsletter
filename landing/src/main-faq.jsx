import React from 'react'
import { createRoot } from 'react-dom/client'
import FaqPage from './FaqPage.jsx'
import './index.css'
/* createRoot().render(), not hydrateRoot(). SPEC 15.2 (proposed) is load
   bearing on this: the prerendered markup exists for readers that are not
   browsers, and React replaces it outright rather than comparing against it,
   so a server and client mismatch is impossible by construction. */
createRoot(document.getElementById('root')).render(<FaqPage />)
