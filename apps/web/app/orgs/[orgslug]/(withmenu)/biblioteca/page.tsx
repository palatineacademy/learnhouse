import { Metadata } from 'next'
import { getOrganizationContextInfo } from '@services/organizations/orgs'
import { getOrgSeoConfig, buildPageTitle } from '@/lib/seo/utils'

type PageParams = Promise<{
  orgslug: string
}>

export async function generateMetadata({
  params,
}: {
  params: PageParams
}): Promise<Metadata> {
  const { orgslug } = await params
  const org = await getOrganizationContextInfo(orgslug, {
    revalidate: 120,
    tags: ['organizations'],
  })

  const seoConfig = getOrgSeoConfig(org)

  return {
    title: buildPageTitle('Biblioteca', org?.name || 'Organization', seoConfig),
    robots: {
      index: false,
      follow: false,
    },
  }
}

export default function BibliotecaPage() {
  return (
    <iframe
      src="https://biblioteca.pltn.com.br"
      title="Biblioteca"
      className="w-full h-[calc(100vh-60px)] border-0"
    />
  )
}
