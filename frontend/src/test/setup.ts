// Test environment: jest-dom matchers plus a clean slate between tests.
// Every component here talks to the backend through fetch, so each test
// installs its own stub and must not inherit the previous one.
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  localStorage.clear()
})
