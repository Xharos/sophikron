// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
import type { Account } from '#lib/types';

declare global {
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
