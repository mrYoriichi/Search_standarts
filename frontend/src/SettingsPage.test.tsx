// The profile form is the one place in the UI that can destroy data the
// user cannot get back: PUT replaces the whole profile, so a form saved
// while empty wipes name, company and position on the license server.
//
// It happened for real (audit 2026-08-06 #4): a failed load returned
// silently, leaving the fields empty and Save enabled — and the license
// server sleeps on Render, so a slow answer is normal, not exotic.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import SettingsPage from './SettingsPage'
import { callsTo, stubApi } from './test/api'

const PROFILE = {
  username: 'anna@example.com',
  email: 'anna@example.com',
  full_name: 'Anna Nova',
  company: 'Mosty s.r.o.',
  position: 'Projektant',
  linkedin: null,
}

function saveButton() {
  return screen.getByRole('button', { name: 'Save profile' })
}

describe('profile form', () => {
  it('fills the fields from the server and sends them back on save', async () => {
    const calls = stubApi({ '/api/auth/profile': { body: PROFILE } })
    render(<SettingsPage />)

    const name = await screen.findByDisplayValue('Anna Nova')
    await waitFor(() => expect(saveButton()).toBeEnabled())

    await userEvent.clear(name)
    await userEvent.type(name, 'Anna Novakova')
    await userEvent.click(saveButton())

    const [put] = callsTo(calls, '/api/auth/profile', 'PUT')
    expect(put.body).toEqual({
      email: 'anna@example.com',
      full_name: 'Anna Novakova',
      company: 'Mosty s.r.o.',
      position: 'Projektant',
      linkedin: '',
    })
  })

  it('cannot be saved while the profile has not loaded yet', async () => {
    stubApi({ '/api/auth/profile': { ok: false, status: 503 } })
    render(<SettingsPage />)

    expect(await screen.findByText('Failed to load the profile.')).toBeVisible()
    expect(saveButton()).toBeDisabled()
  })

  it('never sends a blank profile after a failed load', async () => {
    const calls = stubApi({ '/api/auth/profile': { ok: false, status: 503 } })
    render(<SettingsPage />)

    await screen.findByText('Failed to load the profile.')
    // The click is what a hurried user does; the form must swallow it.
    await userEvent.click(saveButton())

    expect(callsTo(calls, '/api/auth/profile', 'PUT')).toHaveLength(0)
  })
})
