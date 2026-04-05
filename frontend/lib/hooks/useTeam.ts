'use client'

import { create } from 'zustand'

export type TeamScope = 'all' | number

interface TeamStore {
  teamId: TeamScope
  setTeamId: (id: TeamScope) => void
}

export const useTeamStore = create<TeamStore>((set) => ({
  teamId: 'all',
  setTeamId: (teamId) => set({ teamId }),
}))
