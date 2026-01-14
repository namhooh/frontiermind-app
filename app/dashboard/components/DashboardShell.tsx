'use client'

import { useState } from 'react'
import { Sidebar } from './Sidebar'
import { MainContent } from './MainContent'

export function DashboardShell() {
  const [activeSection, setActiveSection] = useState('overview')

  return (
    <>
      <Sidebar activeSection={activeSection} onSectionChange={setActiveSection} />
      <MainContent activeSection={activeSection} onSectionChange={setActiveSection} />
    </>
  )
}
