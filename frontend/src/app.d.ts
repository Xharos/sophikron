// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
import type { Account } from '#lib/types';

declare global {
	const __APP_VERSION__: string;
	const __APP_REVISION__: string | null;
	namespace App {
		// interface Error {}
		interface Locals {
			user: Account | null;
		}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
