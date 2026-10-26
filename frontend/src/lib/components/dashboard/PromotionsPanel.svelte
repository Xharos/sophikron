<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { command, read, promotionCounts } from '#lib/dashboard';
	import type { Page, Promotion, PromotionArchiveImpact } from '#lib/types';
	import Icon from '../Icon.svelte';
	import Pagination from '../Pagination.svelte';
	import AccountsPanel from './AccountsPanel.svelte';
	import PromotionEditor from './PromotionEditor.svelte';
	import MembershipPicker from './MembershipPicker.svelte';
	import PromotionGroups from './PromotionGroups.svelte';
	let {
		administrator,
		currentUserId,
		initialPromotion,
		canReadStudents = true,
		initialEdit = false
	}: {
		administrator: boolean;
		currentUserId: number;
		initialPromotion?: Promotion;
		canReadStudents?: boolean;
		initialEdit?: boolean;
	} = $props();
	let query = $state('');
	let filterState = $state('true');
	let offset = $state(0);
	let total = $state(0);
	let items = $state<Promotion[]>([]);
	let selected = $state<Promotion | null>(untrack(() => initialPromotion ?? null));
	let editor = $state<Promotion | 'new' | null>(
		untrack(() => (initialEdit ? (initialPromotion ?? null) : null))
	);
	let adding = $state(false);
	let confirmArchive = $state(false);
	let archiveStudents = $state(false);
	let impact = $state<PromotionArchiveImpact | null>(null);
	let impactLoading = $state(false);
	let loading = $state(true);
	let busy = $state(false);
	let message = $state('');
	let ready = $state(false);
	let revision = $state(0);
	let groupsDirty = $state(false);
	let groupsRevision = $state(0);
	onMount(() => {
		ready = true;
	});
	$effect(() => {
		const q = query;
		const filter = filterState;
		const page = offset;
		void revision;
		if (!ready) return;
		const controller = new AbortController();
		const timer = setTimeout(
			async () => {
				loading = true;
				message = '';
				try {
					const result = await read<Page<Promotion>>(
						'promotions',
						{ q, is_active: filter || undefined, offset: page, limit: 12 },
						controller.signal
					);
					items = result.items;
					total = result.total;
					if (selected)
						selected = result.items.find((item) => item.id === selected?.id) ?? selected;
				} catch (cause) {
					if (!controller.signal.aborted) message = (cause as Error).message;
				} finally {
					if (!controller.signal.aborted) loading = false;
				}
			},
			q ? 220 : 0
		);
		return () => {
			clearTimeout(timer);
			controller.abort();
		};
	});
	async function openArchive(): Promise<void> {
		if (confirmArchive) {
			confirmArchive = false;
			return;
		}
		if (!selected) return;
		const id = selected.id;
		archiveStudents = false;
		impact = null;
		message = '';
		confirmArchive = true;
		impactLoading = true;
		try {
			const result = await read<PromotionArchiveImpact>('promotionArchiveImpact', { id });
			if (selected?.id === id) impact = result;
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			impactLoading = false;
		}
	}
	async function archive(): Promise<void> {
		if (!selected) return;
		busy = true;
		message = '';
		try {
			selected = await command<Promotion>('updatePromotion', {
				id: selected.id,
				data: {
					is_active: !selected.is_active,
					archive_students: selected.is_active && archiveStudents,
					acknowledge_student_impact: true
				}
			});
			confirmArchive = false;
			revision += 1;
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	function changed(): void {
		revision += 1;
	}
</script>

<section class="workspace-panel">
	<div class="panel-heading">
		<div>
			<p class="eyebrow">Promotions</p>
			<h2 class="title is-4 mb-2">
				{administrator ? 'Vos groupes, au même endroit.' : 'Mes promotions'}
			</h2>
			<p class="muted text-small">
				{administrator
					? 'Créez, organisez et retrouvez vos promotions.'
					: 'Retrouvez les élèves de vos promotions, y compris les comptes archivés.'}
			</p>
		</div>
		{#if administrator}<button class="button is-primary" onclick={() => (editor = 'new')}
				><Icon name="plus" />Nouvelle promotion</button
			>{/if}
	</div>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	{#if selected}
		<button
			class="button is-text mb-4"
			onclick={() => {
				if (groupsDirty && !window.confirm('Quitter sans enregistrer les groupes ?')) return;
				groupsDirty = false;
				selected = null;
				confirmArchive = false;
			}}><Icon name="previous" />Toutes les promotions</button
		>
		<div class="promotion-detail" style={`--promotion-color: ${selected.color}`}>
			<div>
				<span class="eyebrow"
					>{selected.year} · {selected.is_active ? 'Promotion active' : 'Promotion archivée'}</span
				>
				<h3 class="title is-3">{selected.identifier}</h3>
				<p class="muted">
					{promotionCounts(selected)}
				</p>
			</div>
			{#if administrator}<div class="profile-buttons">
					<button class="button is-light" onclick={() => (editor = selected)}
						><Icon name="edit" />Modifier</button
					>
					<button class="button is-light" onclick={openArchive}
						><Icon name={selected.is_active ? 'archive' : 'restore'} />{selected.is_active
							? 'Archiver'
							: 'Réactiver'}</button
					>
					<button
						class="button is-primary"
						disabled={!selected.is_active}
						onclick={() => (adding = true)}><Icon name="plus" />Ajouter des membres</button
					>
				</div>{/if}
		</div>
		{#if confirmArchive}<div class="confirmation-panel mt-4">
				<p class="has-text-weight-semibold">
					{selected.is_active ? 'Archiver cette promotion ?' : 'Réactiver cette promotion ?'}
				</p>
				{#if impactLoading}<p role="status" class="muted mt-2">
						Vérification des comptes concernés…
					</p>
				{:else if impact}
					{#if selected.is_active}
						<p class="muted mt-2">
							Les rattachements et les cours sont conservés. Sans cette option, les membres peuvent
							toujours se connecter.
						</p>
						<label class="checkbox mt-3"
							><input type="checkbox" bind:checked={archiveStudents} disabled={busy} /> Archiver
							également {impact.student_count === 1 ? 'le' : 'les'}
							{impact.student_count} compte{impact.student_count === 1 ? '' : 's'} élève{impact.student_count ===
							1
								? ''
								: 's'} rattaché{impact.student_count === 1 ? '' : 's'}</label
						>
						{#if archiveStudents}<p class="notification is-warning is-light mt-3" role="alert">
								Attention : cette action désactive la connexion de tous les élèves de cette
								promotion, même s’ils appartiennent aussi à une autre promotion. {impact.accounts_to_disable}
								compte{impact.accounts_to_disable === 1 ? '' : 's'}
								{impact.accounts_to_disable === 1 ? 'va' : 'vont'} être désactivé{impact.accounts_to_disable ===
								1
									? ''
									: 's'} ; les sessions seront fermées. Les professeurs, khôlleurs et administrateurs
								restent actifs.
							</p>{/if}
					{:else}
						<p class="notification is-warning is-light mt-3" role="alert">
							Attention : la connexion sera rétablie pour {impact.accounts_to_restore} compte{impact.accounts_to_restore ===
							1
								? ''
								: 's'} désactivé{impact.accounts_to_restore === 1 ? '' : 's'}
							par cette promotion. {impact.accounts_remaining_disabled} compte{impact.accounts_remaining_disabled ===
							1
								? ''
								: 's'}
							{impact.accounts_remaining_disabled === 1 ? 'restera' : 'resteront'} désactivé{impact.accounts_remaining_disabled ===
							1
								? ''
								: 's'}
							en raison d’un archivage manuel ou d’une autre promotion archivée. Les anciens liens d’activation
							et les anciennes sessions ne sont pas rétablis. Les comptes en attente d’activation nécessiteront
							une nouvelle invitation.
						</p>
					{/if}
				{/if}
				<div class="buttons mt-3">
					<button
						class="button is-primary"
						disabled={busy || impactLoading || !impact}
						class:is-loading={busy}
						onclick={archive}>Confirmer</button
					>
					<button class="button is-light" disabled={busy} onclick={() => (confirmArchive = false)}
						>Annuler</button
					>
				</div>
			</div>{/if}
	{:else}
		<div class="list-toolbar">
			<div class="search-field">
				<Icon name="search" /><input
					class="input"
					aria-label="Rechercher une promotion"
					placeholder="Rechercher une promotion…"
					bind:value={query}
					oninput={() => (offset = 0)}
				/>
			</div>
			<div class="select">
				<select
					aria-label="État des promotions"
					bind:value={filterState}
					onchange={() => (offset = 0)}
					><option value="true">Actives</option><option value="false">Archivées</option><option
						value="">Toutes les promotions</option
					></select
				>
			</div>
		</div>
		{#if loading}<p class="loading-state" role="status">
				Chargement des promotions…
			</p>{:else if items.length === 0}<div class="empty-state">
				<Icon name="promotions" size={30} />
				<p>Aucune promotion à afficher.</p>
			</div>
		{:else}<div class="promotion-grid">
				{#each items as promotion (promotion.id)}<button
						class="promotion-card"
						style={`--promotion-color: ${promotion.color}`}
						onclick={() => (selected = promotion)}
					>
						<span class="promotion-card-top"
							><span class="promotion-year">{promotion.year}</span><Icon
								name="open"
								size={14}
							/></span
						>
						<strong>{promotion.identifier}</strong><span class="muted text-small"
							>{promotionCounts(promotion)} · {promotion.is_active ? 'Active' : 'Archivée'}</span
						></button
					>{/each}
			</div>{/if}
		<Pagination {offset} limit={12} {total} busy={loading} onchange={(value) => (offset = value)} />
	{/if}
</section>
{#if selected}
	{#key selected.id}
		<PromotionGroups
			promotion={selected}
			{administrator}
			rosterRevision={revision}
			ondirty={(value) => (groupsDirty = value)}
			onchanged={() => (groupsRevision += 1)}
		/>
	{/key}
{/if}
{#if selected && (administrator || canReadStudents)}{#key selected.id + ':' + revision + ':' + groupsRevision}<AccountsPanel
			{administrator}
			{currentUserId}
			promotionId={selected.id}
			onchanged={changed}
		/>{/key}{/if}
{#if editor}<PromotionEditor
		promotion={editor === 'new' ? undefined : editor}
		onclose={() => (editor = null)}
		onsaved={(promotion) => {
			if (selected?.id === promotion.id) selected = promotion;
			changed();
		}}
	/>{/if}
{#if adding && selected}<MembershipPicker
		promotion={selected}
		onclose={() => (adding = false)}
		onsaved={changed}
	/>{/if}
