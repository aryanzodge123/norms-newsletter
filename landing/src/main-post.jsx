import React from 'react'
import { createRoot } from 'react-dom/client'
import PostPage from './PostPage.jsx'
import './index.css'
/* createRoot().render(), not hydrateRoot(), for the reason main-blog.jsx
   gives: the prerendered markup exists for readers that are not browsers, and
   React replaces it outright rather than comparing against it. */
createRoot(document.getElementById('root')).render(<PostPage />)
