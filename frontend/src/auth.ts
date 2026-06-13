// JWT is kept in sessionStorage (NOT localStorage): sessionStorage is cleared
// when the tab closes and is not shared across tabs, which narrows the XSS
// token-theft window compared to a long-lived localStorage token.
const KEY = 'agentiq_token'

export const getToken = (): string | null => sessionStorage.getItem(KEY)
export const setToken = (token: string): void => sessionStorage.setItem(KEY, token)
export const clearToken = (): void => sessionStorage.removeItem(KEY)
export const isAuthed = (): boolean => Boolean(getToken())
