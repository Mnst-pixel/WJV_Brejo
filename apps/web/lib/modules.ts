import type {IconName} from "@/components/Icon";

export const moduleInfo: Record<string, {title: string; description: string; icon: IconName}> = {
  estudar: {title: "Estudar", description: "Organize leituras, notas e revisão por matéria.", icon: "book"},
  questoes: {title: "Questões", description: "Pratique com versões, fontes e explicações após a resposta.", icon: "question"},
  simulados: {title: "Simulados", description: "Treine com tempo, autosave e regras claras de assistência.", icon: "clipboard"},
  "segunda-fase": {title: "Segunda fase", description: "Estruture peças e respostas a partir de espelhos versionados.", icon: "document"},
  biblioteca: {title: "Biblioteca", description: "Consulte materiais com origem, vigência e revisão humana.", icon: "library"},
  consultor: {title: "Consultor Kairós", description: "Faça perguntas com fonte, data e declaração de incerteza.", icon: "chat"},
  arquivos: {title: "Arquivos", description: "Envie documentos para verificação, antivírus e processamento privado.", icon: "folder"},
  metas: {title: "Metas", description: "Planeje o próximo passo sem perder o histórico.", icon: "target"},
  configuracoes: {title: "Configurações", description: "Controle preferências, privacidade e sessões.", icon: "settings"},
};
