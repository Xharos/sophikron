<script lang="ts">
	import RoleTag from './RoleTag.svelte';
	let { roles }: { roles: string[] } = $props();
</script>

<span class="role-badges">
	{#each roles as role (role)}
		<RoleTag {role} />
	{/each}
</span>

<style>
	.role-badges {
		display: inline-flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		vertical-align: middle;
	}
</style>
