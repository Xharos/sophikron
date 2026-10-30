/** Browser-local presentation preference; never an authentication cookie. */
export type ThemePreference = 'light' | 'system' | 'dark';
export const themeCookie = 'sophikron_theme';

/** Accept only fixed theme identifiers before inserting them into HTML or cookies. */
export function themePreference(value: unknown): ThemePreference {
	return value === 'light' || value === 'dark' ? value : 'system';
}

/** Keep the HTML shell in sync with the request cookie before the first paint. */
export function themedHtml(html: string, preference: unknown): string {
	return html.replace('data-theme="system"', `data-theme="${themePreference(preference)}"`);
}

/** Store the preference, rather than the system's current resolved appearance. */
export function themeCookieValue(preference: ThemePreference, secure: boolean): string {
	return `${themeCookie}=${themePreference(preference)}; Path=/; Max-Age=31536000; SameSite=Lax${secure ? '; Secure' : ''}`;
}
