# Publicação

Aplicação: https://seucomercio-aqui.onrender.com

Cadastro: https://seucomercio-aqui.onrender.com/entrar?cadastro=1

Saúde do servidor e do banco: https://seucomercio-aqui.onrender.com/health

## Infraestrutura

- Render Web Service **seucomercio-aqui**, plano **Free**, Oregon, Docker. O deploy acompanha a branch main deste repositório.
- Supabase **SeuComércioAqui**, projeto `avdxohzqygktcromonqa`, região us-west-2. PostgreSQL e bucket `commerce-photos` guardam os dados fora do disco temporário do Render.
- Conexão PostgreSQL pelo pooler de sessão IPv4, porta 5432. O usuário `seucomercio_backend` possui somente o schema privado `seucomercio`, sem permissão para criar bancos ou usuários.
- Upload pelo backend para a Edge Function `commerce-upload`, que autentica o servidor com um token aleatório validado por SHA-256. As fotos são reprocessadas em WebP. O bucket permite leitura pública das fotos e não possui escrita pública.

As tabelas privadas têm RLS habilitado, sem políticas para usuários da Data API. O backend proprietário das tabelas autentica os lojistas e aplica o isolamento entre lojas. O aviso informativo [RLS enabled no policy](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy) é esperado nessa arquitetura. A função de evento `rls_auto_enable` não concede EXECUTE aos papéis públicos.

## Configuração e manutenção

Os segredos ficam nas variáveis de ambiente do serviço Render: `SECRET_KEY`, `DATABASE_URL` e `STORAGE_UPLOAD_TOKEN`. Não devem ser copiados para este repositório ou para o navegador. A chave administrativa do Supabase permanece no ambiente da Edge Function.

Para republicar a função, configure `UPLOAD_TOKEN_SHA256` com o hash do token do servidor. A publicação inicial incluiu esse hash como fallback no código implantado; o arquivo versionado continua exigindo configuração explícita. A função usa autenticação própria, por isso a verificação JWT da plataforma fica desativada. Ao trocar o token, atualize a função e o Render juntos.

Para começar a usar: crie sua conta, configure contato e pagamentos, cadastre produtos e abra a loja. Cada novo cadastro começa com uma loja fechada e vazia. Não há conta ou senha padrão. Pix é confirmado manualmente pelo lojista; cartão e dinheiro são recebidos na entrega ou retirada.

O Render Free [adormece após 15 minutos sem tráfego e pode levar cerca de um minuto para reabrir](https://render.com/docs/free). As horas gratuitas são compartilhadas pelos serviços do workspace. O [Supabase Free](https://supabase.com/pricing) também tem limites de uso e pode pausar projetos inativos. Não há disco persistente nem recursos pagos contratados nesta publicação.

Backups de produção devem incluir PostgreSQL (`pg_dump`) e as fotos do Storage. `scripts/backup.py` serve apenas para instalações SQLite. Para redefinir uma senha administrativamente, conecte uma execução local às variáveis da produção e use `flask --app app:create_app reset-password --email EMAIL`; não coloque a senha na linha de comando nem nos logs.
