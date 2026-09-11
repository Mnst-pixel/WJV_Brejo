# Biblioteca e anotações pessoais

A biblioteca reúne leituras publicadas e notas privadas. O aluno cria, pesquisa, abre e edita notas usando título, texto, disciplina e tema. A leitura pode iniciar uma nota vinculada àquela publicação revisada. A associação histórica permanece após arquivamento; anexar uma publicação nova exige verificar novamente seu estado e recibo de aprovação. Notas pessoais não são publicações jurídicas.

PostgreSQL é a fonte canônica. Criação usa UUID por conta e hash do pedido original; repetição retorna a nota atual, sem duplicar ou restaurar texto antigo. Edição exige expected_version. O cliente envia expected_owner para impedir que uma mudança de sessão grave o rascunho na conta errada. Locks seguem titular → nota. A listagem é paginada, filtrada pelo titular e usa joins para nomes, sem N+1. Corpo preserva whitespace, limitado a 100 mil caracteres.

Texto não confirmado possui envelope temporário em sessionStorage, separado por conta. Ao recarregar, o editor primeiro confere o servidor. Uma resposta perdida não libera um reenvio cego; conflitos mostram a versão atual e exigem escolha explícita. A gravação é manual e o estado informa quando está confirmada. Não há autosave implícito. Falha no armazenamento temporário é informada; notas confirmadas continuam recuperáveis pelo servidor. Não é prometida recuperação de texto nunca enviado quando a aba e sua cópia temporária forem perdidas.

Migração `0015_personal_note_creation`: vínculo opcional ContentVersion, UUID/hash de criação, unicidade parcial titular/UUID e versão positiva. Dados antigos preservam texto, título, versão, titular e timestamps; vínculos e recibos antigos ficam vazios. Não se inventa provenance para notas antigas. O ensaio histórico de migrations inclui preservação forward/reverse/forward. As corridas reais PostgreSQL são gate do candidato Linux.

Exclusão não está disponível neste recorte. DELETE retorna 405: apagar a linha destruiria o recibo idempotente e permitiria ressuscitar um pedido antigo. Exclusão futura requer versão esperada e tombstone/recibo preservado. Este módulo não oferece histórico completo de todas as edições nem administração do conteúdo privado por terceiros.

Rollback: conservar migration 0015 e notas/recibos ao trocar por artefato compatível. Não reabrir DELETE legado nem gravadores sem versão. Reverter schema em produção apagaria referências e recibos; só ensaiar reversão em banco descartável. Antes de qualquer aplicação real, backup com restore e reconciliação dos grants, sem descarte de notas posteriores ao backup.

Arquivos: personal_notes.py, StudyNote/serializer/viewset, migration 0015, NotesWorkspace/LibraryWorkspace/notes.css, ReadingWorkspace, testes personal_notes/personal_note_concurrency/foundation_migrations e E2E editorial. Estado de testes/imagem/deploy consta em [P3-P6-ENTREGA.md](P3-P6-ENTREGA.md). Não implantado enquanto os gates da release integral estiverem pendentes.
