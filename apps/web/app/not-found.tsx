import { ArrowRight } from 'lucide-react'
import Image from 'next/image'
import Link from 'next/link'
import palatineLogo from 'public/palatine-academy-logo.png'
import { resolveOrg } from '@services/org/orgResolution'
import { getGoogleFontUrl, DEFAULT_FONT } from '@/lib/fonts'

export default async function NotFound() {
  const { org } = await resolveOrg()
  const primaryColor = org?.config?.config?.customization?.general?.color || org?.config?.config?.general?.color || '#000000'
  const customFont = org?.config?.config?.customization?.general?.font || org?.config?.config?.general?.font || ''

  return (
    <div
      className="flex min-h-screen w-full flex-col items-center justify-center
   bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-zinc-200 to-slate-300"
      style={customFont ? { fontFamily: `'${customFont}', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif` } : undefined}
    >
      {customFont && customFont !== DEFAULT_FONT && (
        <link rel="stylesheet" href={getGoogleFontUrl(customFont)} />
      )}
      <div className="flex items-center gap-3 pb-20">
        <Image quality={100}
          width={84}
          height={100}
          src={palatineLogo}
          alt="Palatine Academy logo"
        />
        <span className="text-2xl font-semibold text-black">Palatine Academy</span>
      </div>
      <div className="space-y-6 text-center">
        <h1 className="text-8xl leading-7 font-bold text-black drop-shadow-md">
          404!
        </h1>
        <p className='text-lg pt-8 text-black tracking-tight font-medium leading-normal'>
          Sentimos muito pelo inconveniente. Parece que você está tentando
          <span className="block">acessar uma página que foi removida ou nunca existiu</span>
        </p>
      </div>
      <div className='pt-8 flex flex-col items-center'>
      <Link
        href="/"
        className="flex w-fit h-[50px] text-xl space-x-2 px-6 py-2 text-md rounded-lg font-bold text-white items-center shadow-md gap-2"
        style={{ backgroundColor: primaryColor }}
      >
        Voltar para a página inicial
        <ArrowRight className="tracking-tight transition-transform duration-150 ease-in-out ml-1" />
      </Link>
    </div>
    </div>
  )
}
