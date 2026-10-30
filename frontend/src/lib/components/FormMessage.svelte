<script lang="ts">
	let { message, success = false }: { message?: string; success?: boolean } = $props();
</script>

{#if message}
	<div
		class="notification is-light"
		class:is-danger={!success}
		class:is-success={success}
		role={success ? 'status' : 'alert'}
	>
		{message}
	</div>
{/if}
