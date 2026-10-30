import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import { readFileSync } from 'node:fs';

const { version } = JSON.parse(
	readFileSync(new URL('./package.json', import.meta.url), 'utf8')
) as { version: string };
const revision = process.env.SOPHIKRON_BUILD_REVISION ?? '';

export default defineConfig({
	define: {
		__APP_VERSION__: JSON.stringify(version),
		__APP_REVISION__: JSON.stringify(/^[0-9a-f]{40}(-dirty)?$/.test(revision) ? revision : null)
	},
	plugins: [
		sveltekit({
			adapter: adapter(),
			paths: { origin: process.env.ORIGIN || 'http://localhost:3000' }
		})
	],
	server: {
		watch: {
			usePolling: true,
			interval: 1000
		}
	}
});
