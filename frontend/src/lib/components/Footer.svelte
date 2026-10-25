<script lang="ts">
	let { establishmentName }: { establishmentName: string } = $props();
</script>

<footer class="site-footer">
	<div class="container footer-content">
		<p><strong>{establishmentName}</strong> <span class="muted">· Apprendre, ensemble.</span></p>
		<p class="muted">Logiciel libre · GNU GPL v3.0</p>
	</div>
</footer>
