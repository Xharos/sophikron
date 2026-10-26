<script lang="ts">
	import ThemePicker from './ThemePicker.svelte';
	import type { ThemePreference } from '#lib/theme';
	let {
		establishmentName,
		themePreference = 'system'
	}: { establishmentName: string; themePreference?: ThemePreference } = $props();
</script>

<footer class="site-footer">
	<div class="container footer-content">
		<p><strong>{establishmentName}</strong> <span class="muted">· Apprendre, ensemble.</span></p>
		<p class="muted">Logiciel libre · GNU GPL v3.0</p>
		<ThemePicker initialPreference={themePreference} />
	</div>
</footer>
