var saveSearchOnStorage = JSON.parse(localStorage.saveSearchOnStorage || null) || {};

var SearchFlightBluekaiController = {
	    formatDate : function(data) {
	        var dia = SearchFlightBluekaiController.dateDigits(data.getDate());
	        var mes = SearchFlightBluekaiController.dateDigits(data.getMonth() +1);
	        var ano = SearchFlightBluekaiController.dateDigits(data.getFullYear());
	        var formatedDate = mes + '/' + dia + '/' + ano;
	        return formatedDate;
	    },

	    dateDigits : function(param) {
	        param = "" + param;
	        if (param.length == 1) {
	            param = "0" + param;
	        }
	        return param;
	    }
	};

var SearchFlightController = {
    version              : '2.44',
    searchAirportEnabled : null,
    lastSearchAirports   : {},
	elegibilityURL		 : null,
	executeSearchURL	 : null,
	searchAirportURL	 : null,
	namespace 			 : null,
	airportsJsonOriginal : null,
	airportsJsonStrip    : null,
	tooltipcount		 : 1,
	tripType 	   		 : null,
	adults   	   		 : null,
	children 	   		 : null,
	totalPassenger		 : null,
	departureDay1 		 : null,
	departureDay2 		 : null,
	returnDay     		 : null,
	originAirport 		 : null,
	destinAirport 		 : null,
	tripOAirport  		 : null,
	tripDAirport  		 : null,
	loadingModal		 : null,
    maxAge               : 3600,   
	listAirports		 : {},
    lsAvailable          : true,
    firstDownload        : false,
    changeDestination    : null,
    jsonValidateCredentials:null,
    requestHeaderXApiKey : null,
    isFlexibleDateChecked:false,
    flexibleDateOptions:null,
    statusTooltipMobile:false,
    dataAirportOrigin	 : "",
    dataAirportDeparture	 : "",
    cabin: null,
    featureFlagEnabled: false,

    loadPage : function() {
        SearchFlightController.msgLog("Versão: " + this.version , "info");

        if($("#single-leg").is(':checked')){
            $('#single-leg').prop('checked', false).removeAttr('checked');              
        }

        //Verifica se o localStorge esta disponivel
        if (typeof localStorage === 'object') {
            try {
                localStorage.setItem('localStorage', 1);
                localStorage.removeItem('localStorage');
            } catch (e) {
                SearchFlightController.lsAvailable = false;
                SearchFlightController.msgLog("Localstorage nao disponivel", "info");
            }
        }

        try {
            if (!window.location.pathname.includes('emissao-com-milhas')) {
                sessionStorage.removeItem('descubraReferral');
            }
        } catch (e) {
            console.log(e);
        }

        if (document.querySelector('meta[name="deviceMobile"]').getAttribute('content').toLowerCase() == "true") {
            $("#inputGoingOriginDate").attr("type","date");
            $("#inputBackDate").attr("type","date");
            $("#inputMoreGoingOriginDate").attr("type","date");
            $('.searchFlightL').before($('#findSearch'));
            $('.searchFlight:first').find('.searchFlightKMobile').addClass('searchFlightK').before( $('.roundTrip').addClass('input-full'));
        } else {
            $("#inputGoingOriginDate").attr("type","text");
            $("#inputBackDate").attr("type","text");
            $("#inputMoreGoingOriginDate").attr("type","text");
            $('.searchFlight:first').find('.searchFlightKMobile').css('display','block');
        }

        var inputSearchOrigin = $("input#inputOrigin");
        var inputSearchDestination = $("input#inputDestination");
        var ulSuggestionAirportOrigin = SearchFlightController.buildSearchAirport("#searchFlightTab","searchFlightTabBackCInter","ulOriginAirport");
        var ulSuggestionAirportDestination = SearchFlightController.buildSearchAirport("#searchFlightTabBack","searchFlightTabBackCInter","ulDestinationAirport");

        SearchFlightController.loadBehaviorKey(inputSearchOrigin, "#searchFlightTab",ulSuggestionAirportOrigin);
        SearchFlightController.loadBehaviorKey(inputSearchDestination, "#searchFlightTabBack",ulSuggestionAirportDestination);

        SearchFlightController.loadAirportList( function() {
	        SearchFlightController.msgLog("Carregando os scripts da página", "info");
	        SearchFlightController.loadElements(function() {
	            SearchFlightController.loadAutomaticAirport();
	            SearchFlightController.changeTypeFlight();
	            SearchFlightController.changeOriginDate();
	            SearchFlightController.removeWidthError();
	            BookingCalendarController.loadHomeCalendar();
	            BookingCalendarController.controlDateRange();
	            SearchFlightController.loadListeningSubmitButton();
	            SearchFlightController.msgLog("Scripts da página carregados", "info");
	        });
        });

        SearchFlightController.inputListener();
        SearchFlightController.milesBalanceSearch();
    },   

    loadListeningSubmitButton: function(){
        $('#submitFlightSearch').on('click', function () {
            try {
                eventStoptBookingTimer();
            } catch (e) {
                console.log('error', e)
            }
            // Seta tripType
            SearchFlightController.tripType = SearchFlightController.getTripTypeCodeOrId($("#smls-widget-home #selectType").val());
            // Verifica data de volta (se foi selecionada ou não)
            if( SearchFlightController.tripType === '1' && $('#'+BookingCalendarController.namespace+'return_date').val() === '' ){
                SearchFlightController.errorAlert('label.search.flight.validate.no.return.date');
            }else{
                // Verifica se é multiplos destinos e as pernas escolhidas são diferentes (G3xCongenere ou CongenerexG3)
                if( !SearchFlightController.isMultipleLegsValid() && SearchFlightController.tripType === '3' ){
                    SearchFlightController.checkHistoryMyTravel();
                    SearchFlightController.showModalFlightSearchWarning();
                }else{
                    SearchFlightController.checkHistoryMyTravel();
                    SearchFlightController.validateForm();
                }
            }
        });
    },

    milesBalanceSearch: function() {
        if (window.location.href.includes("passagens")) {
            // Implementa ancora para cards do descubra seu novo destino
            if (localStorage.getItem("backFromBalance") == "true") {
                localStorage.removeItem("backFromBalance");

                const element = "#lppassagens_descubradestino_content_cards";
                interval = setInterval(function() {
                    if ($(element).length && $(element).offset().top > 0) {
                        $([document.documentElement, document.body]).animate({
                            scrollTop:($(element).offset().top + 230 - $(element).height())
                        }, 500, function() {
                            clearInterval(interval);
                        });
                    }
                }, 1000);
            }

            setTimeout(() => {
                // chama a api para pegar as categorias
                MilesBalanceSearchController._request(
                    'get',
                    '/flight/category',
                    null,
                    function(data) {
                        const elements = document.querySelectorAll('#lppassagens_descubradestino #lppassagens_descubradestino_content #lppassagens_descubradestino_content_cards');
                        if (elements && elements[0].children.length > 0 && data) {
                            const cards = elements[0].children;
                            for (key in cards) {
                                const card = cards[key];
                                if (parseInt(key) < 7) {
                                    const link = $(`.${card.className} .lppassagens_descubradestino_content_card_img a`)[key];
                                    const tarja = $(`.${card.className} .lppassagens_descubradestino_content_card_tarja h6`)[key];
                                    const title = tarja ? tarja.textContent.trim() : "";
                                    const category = data.flightCategoryList.find(c => c.name == title);

                                    link.href = '#';
                                    link.addEventListener('click', e => e.preventDefault());
                                    link.removeAttribute('rel');
                                    link.removeAttribute('target');
                                    link.addEventListener("click", function() {
                                        // Clean content
                                        var newContent = category.content;

                                        if(!newContent) {
                                            category.content = {};
                                        } else if (newContent.Description) {
                                            var description = $(newContent.Description);
                                            var author = description.find("ins").text();
                                            
                                            description.find("ins").remove();
                                            description = description.text();

                                            newContent.Description = $.trim(description.toUpperCase());
                                            newContent.Author = $.trim(author.toUpperCase());
                                            category.content = newContent;
                                        }

                                        const ticket = {
                                            "category": {
                                                "code": category.code,
                                                "name": category.name,
                                                "content": category.content,
                                            }
                                        };

                                        MilesBalanceSearchController.filterData = {
                                            ...MilesBalanceSearchController.filterData,
                                            "category": {
                                                "code": category.code,
                                                "name": category.name,
                                                "content": category.content,
                                            }
                                        }

                                        localStorage.setItem("filterData", JSON.stringify(MilesBalanceSearchController.filterData));
                                        localStorage.setItem("ticketCode", JSON.stringify(ticket));
                                        localStorage.setItem("ticketPath", "passagens");
                                        window.open(window.location.origin + "/descubra-seu-novo-destino?passagens=" + title.toLowerCase(), "_parent");
                                    });

                                    // Adiciona lista de categorias para filtro da busca na tela de resultados
                                    MilesBalanceSearchController.filterData = {
                                        "categories" : data.flightCategoryList,
                                    }
                                    localStorage.setItem("filterData", JSON.stringify(MilesBalanceSearchController.filterData));
                                }
                            }
                        }
                    }
                );
            }, 500);
        }
    },

	//Carrega funcionalidades da pagina
	loadElements: function(callback){

		//Trabalha lista de Aeroportos
        SearchFlightController.airportsJsonOriginal  = this.getAirports(SearchFlightController.listAirports);
		SearchFlightController.airportsJsonStrip 	 = this.cleanCharacterSpecial(SearchFlightController.airportsJsonOriginal);
        SearchFlightController.listAirports          = JSON.parse(SearchFlightController.listAirports);

        //+Segments
        var inputSearchOrigin = $("input#inputOriginMs2");
        var inputSearchDestination = $("input#inputDestinationMs2");
        var ulSuggestionAirportOrigin = SearchFlightController.buildSearchAirport("#searchFlightTabMs","searchFlightTabBackCInter","ulOriginAirport");
        var ulSuggestionAirportDestination = SearchFlightController.buildSearchAirport("#searchFlightTabBackMs","searchFlightTabBackCInter","ulDestinationAirport");
        SearchFlightController.loadBehaviorKey(inputSearchOrigin, "#searchFlightTabMs",ulSuggestionAirportOrigin);
        SearchFlightController.loadBehaviorKey(inputSearchDestination, "#searchFlightTabBackMs",ulSuggestionAirportDestination);

        var inputTripType = $(".single-leg label");
        SearchFlightController.loadBehaviorTripTypeKey(inputTripType);

        SearchFlightController.segmentSize = 0;
        var inputMultipleSegmengts = $("a.button-add-new-leg");
        SearchFlightController.loadBehaviorMultipleSegmentsKey(inputMultipleSegmengts);

        inputMultipleSegmengts = $("a.button-from-to");
        SearchFlightController.loadBehaviorRoundTrip(inputMultipleSegmengts);

        var inputRemoveLeg = $("a.remove-leg");
        SearchFlightController.loadBehaviorRemoveLeg(inputRemoveLeg);

        //finalize modeling the elements by tripType
        if (SearchFlightController.tripType == '2') {
            //change the value just to keep the behavior of the function
            SearchFlightController.tripType = '0';
            SearchFlightController.buildTripTypeHTML();
            if (!$('#single-leg').is(':checked')) {
                $('#single-leg').attr("checked", true);
            }

        } else if (SearchFlightController.tripType == '3') {
            SearchFlightController.buildMultipleSegmentsHTML();
        } else if (SearchFlightController.tripType == '1'){
        	$('#single-leg').attr("checked", false);
        }

        callback();
    },

    /**
     * Carrega a lista de Aeroportos no objeto listAirports com os dados do LocalStorage
     * 
     * @method SearchFlightController.loadAirportList
     * @param {function} callback: funcao a ser excutada apos a leitura da lista de aeroportos
     */    
    loadAirportList: function(callback) {
    	if (SearchFlightController.searchAirportEnabled === 'true') {
    		if (SearchFlightController.lsAvailable) {
    			localStorage.removeItem("last-update");
        		if (localStorage.getItem("airport-list") === null || localStorage.getItem("airport-list") === "") {
        	    	SearchFlightController.listAirports = JSON.stringify([]);
            		localStorage.setItem("airport-list", SearchFlightController.listAirports);
        		} else {
        			SearchFlightController.listAirports = localStorage.getItem("airport-list");
        		}
        	}
    		callback();
    	} else {
            if (localStorage.getItem("airport-list") === null || localStorage.getItem("airport-list") === "" 
            		|| (localStorage.getItem("airport-list").match(/{/g) || []).length < 100) {
                SearchFlightController.firstDownload = true ;
                SearchFlightController.getAirportList( function() {
                    if (SearchFlightController.lsAvailable) {
                        localStorage.setItem('airport-list', SearchFlightController.listAirports);
                    }
                    callback();
                });
            } else {
                SearchFlightController.listAirports = localStorage.getItem('airport-list');
                callback();
            }
    	}
    }, 

    /**
     *
     * Forca o reload da lista completa dos aerportos uma vez por dia 
     * 
     */
    forceDownload: function() {
        var update = false;
        if (localStorage.getItem("last-day") === null || localStorage.getItem("last-day") != SearchFlightController.currentDate()) {
            localStorage.setItem("last-day", SearchFlightController.currentDate());
           update = true; 
        }
        return update;
    },

    /**
     * Verifica a data da ultima atualizacao da Lista de Aeroportos. 
     * Caso a data seja diferente, sera feito no novo donload da lista para o LocalStorage
     * IMPORTANTE:
     * A lista sera atualizada no DROPDOWN no proximo reload da pagina
     * @method SearchFlightController.checkLastUpdate
     * @param {function} callback: funcao a ser excutada apos verificar a data
     */     
    checkLastUpdate: function() {
        SearchFlightController.msgLog("Verificando a última data de atualização", "info");           
        
        SearchFlightController.getLastUpdate(function(update) {
            if ((update || SearchFlightController.forceDownload()) && !SearchFlightController.firstDownload) {
                SearchFlightController.getAirportList(function(){
                    SearchFlightController.msgLog("Lista de foi aeroportos atualizada no localStorage", "info");
                });
            }
        });
    },

    /**
     * Consulta a ultima da atualizacao da lista de Aeroportos e compara com a data do LocalStorage
     * Caso o data do LocalStorage esteja em branco ou a data seja diferente, um novo dawlonad da lista 
     * sera feito no para o LocalStorage
     * @method SearchFlightController.getLastUpdate
     * @param {function} callback: funcao a ser excutada apos a resposta do servidor  
     */
    getLastUpdate: function(callback) {
        var localLastUpdate = localStorage.getItem("last-update")
        ,   upadteList      = false
        ,   ts              = +new Date;

        try {         
           if (localStorage.getItem("last-check") > ts) {
                callback(upadteList);
                return;
            }
        }
        catch(err) {
            SearchFlightController.msgLog("Erro ao verificar o timestamp", "error");
        }             

        SearchFlightController.msgLog("Timestamp expirado", "info");       
 
        localStorage.setItem('last-check', ts + (SearchFlightController.maxAge * 1000));                                

        $.ajax ({
            url: SearchFlightController.getListUpdateURL,
            type: "GET",
            success: function(data) {
                if ((data !== localLastUpdate) && (data !== null)) {
                    SearchFlightController.msgLog("Data atualizada", "info");       
                    if(localStorage.getItem("last-update") !== null) {
                      upadteList = true;  
                    }
                    localStorage.setItem("last-update", data);
                }
                callback(upadteList);
            },           
            error: function (jqXHR, exception) {
                SearchFlightController.msgLog("Erro: " + exception, "error");       
            }
        });
    },

    /**
     * Faz o download da lista de Aeroportos quando a lista estiver vazia ou a data da 
     * ultima atualizacao for diferente da data armazenado no LocalStorage
     * @method SearchFlightController.getAirportList
     * @param {function} callback: funcao a ser excutada apos o download da lista
     */
    getAirportList: function(callback) {
        SearchFlightController.msgLog("Fazendo o download da nova lista de aeroportos", "info");
        $.ajax ({
            url: SearchFlightController.executeAirportSearchURL,
            type: "GET",
            success: function(data) {
                var  obj            = JSON.parse(data)
                  ,  airportList    = [];
                
                $.each(obj, function(k, v) {
                    airportList.push({ 
                        city: v.city, 
                        code: v.code,
                        congenere: v.congenere,
                        country: v.country,
                        description: v.description, 
                        g3: v.g3,
                        name: v.name,
                        order: v.order
                    });
                });

                var newListAirports = JSON.stringify(airportList);
                SearchFlightController.listAirports = newListAirports;
                if (SearchFlightController.lsAvailable) {
                    
                    localStorage.setItem("airport-list", newListAirports); 

                    var airportsJsonOriginal = SearchFlightController.getAirports(newListAirports);
                    var airportsJsonStrip = SearchFlightController.cleanCharacterSpecial(airportsJsonOriginal);
                    
                    SearchFlightController.airportsJsonOriginal = airportsJsonOriginal;
                    SearchFlightController.airportsJsonStrip = airportsJsonStrip;
                }                
                callback();                    
            },
            error: function (jqXHR, exception) {
                SearchFlightController.msgLog("Erro: " + exception, "error");       
            }
        });
    },

    /**
     * Consulta os atributos da lista de Aeroportos com base no codido do Aeroporto
     * @method SearchFlightController.getInfoByCode
     * @param {string} code: Codigo do aeroporto
     * @param {string} field: Attributo a ser consultado na lista de Aeroportos
     */
    getInfoByCode: function(code, field) {
        var i,
            len = SearchFlightController.listAirports.length;

        for (i = 0; i < len; i++) {
            if (SearchFlightController.listAirports[i].code === code) {
                return encodeURI(SearchFlightController.listAirports[i][field]);
            }
        }
        return null;
    },

   /**
     * retorna os atributoso do aeroporto com base no codido do Aeroporto
     * @method SearchFlightController.getAirportByCode
     * @param {string} code: Codigo do aeroporto
     */
    getAirportByCode : function(code) {
        var airports = [];
        if (SearchFlightController.listAirports) {
            airports = (typeof SearchFlightController.listAirports == 'string') ? JSON.parse(SearchFlightController.listAirports) : SearchFlightController.listAirports;
        }
        for (var airportIndex = 0; airportIndex < airports.length; airportIndex++) {
            var airport = airports[airportIndex];
            if (airport.code == code) {
                return airport;
            }
        }
    },

    /**
     * Permite exibir as mensagens na console do Browser
     * IMPORTANTE:
     * Para exibir as mensagens dever ser incuido no paramento debugMode=1 na URL
     * Exemplo:
     * https://www.smiles.com.br/home?debugMode=1
     * @method SearchFlightController.debugMode
     */
    debugMode: function() {     
        return SearchFlightController.getParameterByName("debugMode") == 1 ?  true : false;
    },

    /**
     * Recupera qualquer valor de um parametro na URL
     * @method SearchFlightController.getParameterByName
     * @param {string} name: Nome do parametro a ser consultado na URL
     * @param {string} url: URL a ser consultada, quando for omitida busca na URL atual
     */
    getParameterByName: function(name, url) {
        if (!url) url = window.location.href;
        name = name.replace(/[\[\]]/g, "\\$&");
        
        var regex = new RegExp("[?&]" + name + "(=([^&#]*)|&|#|$)"),
            results = regex.exec(url);
        
        if (!results) return null;
        if (!results[2]) return '';
        
        return decodeURIComponent(results[2].replace(/\+/g, " "));
    },

    
    msgLog: function(message, type) {
        var msg = "[BOOKING] " + message;
        
        if (SearchFlightController.debugMode()) {
            switch (type) {
            case "warn":
                console.warn(msg);
                break;
            case "error":
                console.error(msg);
                break;
            case "info":
                console.info(msg);
                break;
            default:
                console.log(msg);
                break;
            }
        }
    },

    currentDate: function() {
		var newDate = new Date();
		return ("0" + newDate.getDate()).substr(-2) + "/"  +
					 ("0" + (newDate.getMonth() + 1)).substr(-2) + 
					 "/" + newDate.getFullYear();
	},
   

	loadBehaviorTripTypeKey : function(inputSearch) {
        inputSearch.click(function() {
            SearchFlightController.buildTripTypeHTML();
        });
    },

    buildTripTypeHTML : function(didReload) {
        SearchFlightController.segmentSize = 0;
        var target = $('.searchable-content.searchable-content-flights');
        var isMobile = $('meta[name="deviceMobile"]').attr('content').toLowerCase() === "true";
        if (SearchFlightController.tripType == '2') {

            if (!didReload) {
            	SearchFlightController.tripType = '2';
            	BookingCalendarController.tripType = '2';
            }
            
            target.removeClass('from-to multiple-legs').addClass('one-leg');
            $('#'+BookingCalendarController.namespace+'return_date').val("");

            if( isMobile ){
                $("#smls-widget-home .dates .go").addClass("multiple-date").removeClass("date");
            }

        } else {
        	if (!didReload) {
        		SearchFlightController.tripType = '1';
        		BookingCalendarController.tripType = '1';
        	}
            target.removeClass('one-leg multiple-legs').addClass('from-to');

            if( isMobile ){
                $("#smls-widget-home .dates .go").addClass("date").removeClass("multiple-date");
            }

            //  se data de volta está nula, chamar o processo de initialização desse campo
            var calendar = BookingCalendarController.loadCalendar('#'+BookingCalendarController.namespace+'departure_date'
                ,'#'+BookingCalendarController.namespace+'departure_wknd'
                ,'#'+BookingCalendarController.namespace+'departure_day'
                ,'#'+BookingCalendarController.namespace+'departure_month')


            var calendar1 = BookingCalendarController.loadCalendar('#'+BookingCalendarController.namespace+'return_date'
                ,'#'+BookingCalendarController.namespace+'return_wknd'
                ,'#'+BookingCalendarController.namespace+'return_day'
                ,'#'+BookingCalendarController.namespace+'return_month');

            var calendars = [calendar, calendar1];
            BookingCalendarController.initialiseFields(calendars);
        }

        if( $("#tripTypeSelectPosition1").html() == "" && !isMobile ){
            var btn = $(".submitFlightSearchBtn");
	        var newBtn = btn.clone();
			$("#tripTypeSelectPosition1").html(SearchFlightController.getTripTypeSelectHtml());
			$("#tripTypeSelectPosition2").html("");
			selectToAbSelect($("#smls-widget-home #selectType"));
			$(".cabins-and-go").append(newBtn);
            btn.remove();
            SearchFlightController.loadListeningSubmitButton();
		}
    },

    loadBehaviorMultipleSegmentsKey : function(inputSearch) {
        inputSearch.click(function() {
            //limita a acao do bota
            if (SearchFlightController.segmentSize == 0) {
                SearchFlightController.buildMultipleSegmentsHTML();
            }
        });
    },

    buildMultipleSegmentsHTML : function() {
        //limita a acao do bota
        if (SearchFlightController.segmentSize == 0) {
            SearchFlightController.segmentSize = 1;

            //seta triptype 3
            SearchFlightController.tripType = '3';
            BookingCalendarController.tripType = '3';

            var target = $('.searchable-content.searchable-content-flights');
            target.removeClass('from-to one-leg').addClass('multiple-legs');

            $('#'+BookingCalendarController.namespace+'return_date').val("");

            if ($('meta[name="deviceMobile"]').attr('content').toLowerCase() != "true") {
                var btn = $(".submitFlightSearchBtn");
                var newBtn = btn.clone();

                $("#tripTypeSelectPosition1").html("");
                $("#tripTypeSelectPosition2").html("");
                if ($('#tripTypeSelectPosition1').find('.container-input.select-container').html())
                    $("#tripTypeSelectPosition1").html("");
                if (!$('#tripTypeSelectPosition2').find('.container-input.select-container').html()) {
                    $("#tripTypeSelectPosition2").html(SearchFlightController.getTripTypeSelectHtml());
                    selectToAbSelect($("#smls-widget-home #selectType"));
                }
                $(".cabins-and-go").after(newBtn);
                btn.remove();
                SearchFlightController.loadListeningSubmitButton();
            }

            var calendar = BookingCalendarController.loadCalendar('#'+BookingCalendarController.namespace+'ms1_date'
                ,'#'+BookingCalendarController.namespace+'ms1_wknd'
                ,'#'+BookingCalendarController.namespace+'ms1_day'
                ,'#'+BookingCalendarController.namespace+'ms1_month')


            var calendar1 = BookingCalendarController.loadCalendar('#'+BookingCalendarController.namespace+'ms2_date'
                ,'#'+BookingCalendarController.namespace+'ms2_wknd'
                ,'#'+BookingCalendarController.namespace+'ms2_day'
                ,'#'+BookingCalendarController.namespace+'ms2_month');

            var calendars = [calendar, calendar1];
            BookingCalendarController.initialiseFields(calendars);
        }
    },

    getTripTypeSelectHtml : function(){
        return `<div class="container-input select-container">
            <select class="ab-select" name="type" id="selectType">
                <option value="go-and-back">` + '\u0049\u0064\u0061\u0020\u0065\u0020\u0056\u006f\u006c\u0074\u0061' + `</option>
                <option value="one-way">` + '\u0053\u006f\u006d\u0065\u006e\u0074\u0065\u0020\u0049\u0064\u0061' + `</option>
                <option value="multiple">` + '\u004d\u0026\u0075\u0061\u0063\u0075\u0074\u0065\u003b\u006c\u0074\u0069\u0070\u006c\u006f\u0073\u0020\u0044\u0065\u0073\u0074\u0069\u006e\u006f\u0073' + `</option>
            </select>
        </div>`;
    },

    loadBehaviorRoundTrip : function(inputSearch) {
        inputSearch.click(function() {
            SearchFlightController.buildRoundTripHTML();
        });
    },

    loadBehaviorRemoveLeg : function(inputSearch) {
        inputSearch.click(function() {
            SearchFlightController.buildRoundTripHTML();
        });
    },

    buildRoundTripHTML : function() {
        SearchFlightController.tripType = '1';
        SearchFlightController.segmentSize = 0;
        var target = $('.searchable-content.searchable-content-flights');
        target.removeClass('multiple-legs one-leg').addClass('from-to');

        //Remove
        var id = '#' + SearchFlightController.namespace + 'divPlusSegments';
        $(id).css('display','none');

        //Retorna checkbox one leg
        id = '#' + SearchFlightController.namespace + 'single-leg';
        $(id).css('display','');

        //devolve primeiro botao add segments
        id = '#' + SearchFlightController.namespace + 'button-add-new-leg';
        $(id).css('display','');

        /* reinicializa calendarios para o cenario de ROUND-TRIP */
        BookingCalendarController.tripType = SearchFlightController.tripType;
        var calendar = BookingCalendarController.loadCalendar('#' + BookingCalendarController.namespace + 'departure_date'
            , '#' + BookingCalendarController.namespace + 'departure_wknd'
            , '#' + BookingCalendarController.namespace + 'departure_day'
            , '#' + BookingCalendarController.namespace + 'departure_month')

        var calendar1 = BookingCalendarController.loadCalendar('#' + BookingCalendarController.namespace + 'return_date'
            , '#' + BookingCalendarController.namespace + 'return_wknd'
            , '#' + BookingCalendarController.namespace + 'return_day'
            , '#' + BookingCalendarController.namespace + 'return_month');

        var calendars = [calendar, calendar1];
        BookingCalendarController.initialiseFields(calendars);
    },

    //Carrega descricao da lista de Aertoportos
	getAirports : function(data){
		var jqueryAirports = jQuery.parseJSON(data);
		var lista = '';
		for(var i=0; i<jqueryAirports.length; i++){
			lista += this.clearDuplicateSpace(jqueryAirports[i].description);
			lista += '\n';
		}
		return lista;
	},

	//Limpa espacos duplicados
	clearDuplicateSpace : function(data){
		var newData = data.replace("  ", " ");
		newData = newData.replace("&nbsp;", " ");
		return newData;
	},

	//Inicia calendarios com as datas atuais
	startDefaultDate : function(fieldDate, fieldDateMonth) {
        var date = new Date();
        $(fieldDate).html(date.getDate());
        $(fieldDateMonth).html(getMonth(date.getMonth() + 1));
    },

    //Limpa caracter especial
	cleanCharacterSpecial : function(texto){
		texto = texto.toLowerCase();
		texto = texto.replace(/[á|ã|â|à]/gi, "a");
		texto = texto.replace(/[é|ê|è]/gi, "e");
		texto = texto.replace(/[í|ì|î]/gi, "i");
		texto = texto.replace(/[õ|ò|ó|ô]/gi, "o");
		texto = texto.replace(/[ú|ù|û]/gi, "u");
		texto = texto.replace(/[ç]/gi, "c");
      	texto = texto.replace(/[ñ]/gi, "n");
      	return texto;
 	 },

 	//Limpa caracter minusculo
 	cleanDownCharacterSpecial : function(texto){
	      texto = texto.toLowerCase();
	      texto = texto.replace(/[\(]/gi, "");
	      texto = texto.replace(/[\)]/gi,"");
	      texto = texto.replace(/[\?|\\\/]/gi,"");
	      return texto;
	},

 	buildSearchAirport : function(idDivParent,divClass,idUlAirport){
        var spanSuggestion = $("<span></span>").addClass("whiteArrowUpTwo");
       	var divSuggestion = $("<div></div>").addClass(divClass);
       	var ulSuggestion = $("<ul></ul>").attr('id',idUlAirport);
       	divSuggestion.append(ulSuggestion);
       	$(idDivParent).append(spanSuggestion,divSuggestion);
       	return ulSuggestion;
     },

     //Acoes referente as buscas dos aeroportos
    loadBehaviorKey : function(inputSearch, idDivParent,ulSuggestionAirport) {
        inputSearch.keyup(function(event) {
            if( $(this).val() !== '') {
                if (event.key !== "Meta") {
                    SearchFlightController.updateSuggestionBox(inputSearch,ulSuggestionAirport);
                    inputSearch.parent().find(".btnClear").show();

                    if(event.key != "Tab") {
                        SearchFlightController.displayFlightTab(idDivParent, this, ulSuggestionAirport);
                    }
            	}
            }else{
                inputSearch.parent().find(".searchFlightTab").hide();
                inputSearch.parent().find("ul").html('');
                inputSearch.parent().find(".btnClear").hide();
                SearchFlightController.manageChatBall("show");
            }
        });

        inputSearch.keypress(function(){        	
        	SearchFlightController.displayFlightTab(idDivParent, this, ulSuggestionAirport);
        });

        inputSearch.keydown(function(event){
            if( event.keyCode === 9 ) {
                event.preventDefault();
                SearchFlightController.onInputTab($(this));
            }
        });

        inputSearch.focus(function() {
            
            var goTo = 0;

            switch(inputSearch.attr('id')){
                case "inputOrigin" :
                    goTo = 120;
                    $("label[for='inputDestination'], #inputDestinationIcon").hide();
                break;
                case "inputDestination" :
                    goTo = 220;
                break;
                case "inputOriginMs2" :
                    goTo = $(this).offset().top - 105;
                    $("label[for='inputDestinationMs2'], #inputDestinationIconMs2").hide();
                break;
                default : 
                    goTo = $(this).offset().top - 105;
                break;
            }

            var winH = window.innerWidth;
            if( winH <= 767 ){
            	$('html, body').animate({scrollTop: goTo + 'px'}, 'fast');
            }

            SearchFlightController.searchInputEfectIn(inputSearch);
            SearchFlightController.showClearButtonOnFocus(inputSearch.attr('id'));
        });

    },
    showClearButtonOnFocus: function(inputId){
        var clean = "#clean_" + inputId;
        if( $('meta[name="deviceMobile"]').attr('content').toLowerCase() !== "true" ){
            $(clean).animate({marginRight: '-30%', right: 25}, 'fast');
        }
    },
    hideClearButtonOnBlur: function(inputId){
        var clean = "#clean_" + inputId;
        if( $('meta[name="deviceMobile"]').attr('content').toLowerCase() !== "true" ){
            $(clean).hide();
            $(clean).animate({marginRight: 25, right: 0}, 100, function(){
                if( $("#"+inputId).val() !== '' ){
                    $(clean).show();
                }
            });
        }
    },
    manageChatBall: function(action){
        if( $('meta[name="deviceMobile"]').attr('content').toLowerCase() === "true" ){
            if( action === 'show' ){
                $("#web-messenger-container").css("display", "block");
            }else{
                $("#web-messenger-container").css("display", "none");
            }
        }
    },

    searchInputEfectIn: function (input) {
        setTimeout(function(){
            $(input).removeClass("focus");
        }, 100);
        $(input).addClass("focus2");
        if (input) {
            $(input).parent().find("label").addClass('focus');
        }
    },

    searchInputEfectOut: function (input) {
        if ( input.val() == '' ) {
            input.parent().find("label").removeClass('focus');
        }
        input.parent().find(".searchFlightTab").hide();
        input.removeClass("focus2");
        SearchFlightController.hideClearButtonOnBlur(input.attr('id'));
        SearchFlightController.manageChatBall("show");
    },

    inputListener: function(){
        $("body").click(function(e){
            var input = $("#smls-widget-home input.focus2");
            var target = e.target;
            var parent = $(target).parents(".label-from-to");
            var parentSuggs = $(target).parents(".searchFlightTab");
            if( input.length === 1 ){
                if(
                    $(target).attr('id') === input.attr('id') ||
                    $(target).attr('id') === 'clean_' + input.attr('id') ||
                    parentSuggs.length > 0 ||
                    $(target).is('.btn', '.right') // Previne fechamento ao trocar de banner: $("#atomoKV .btn.right").click()
                ){
                    if( parentSuggs.length > 0 ){
                        SearchFlightController.excuteClickSuggestionBox($(target).text(), parent.find("input[type='text']"));
                        SearchFlightController.nextInputFocus(input.attr('id'));
                    }
                }else{
                    SearchFlightController.onInputClose(input);
                }
            }else if( input.length > 1 ){
                $(input).each(function(){
                    // Fecha outros inputs abertos caso exista
                    if( $(this).attr('id') !== $(target).attr('id') ){
                        SearchFlightController.onInputClose($(this));
                    }
                });
            }
        });
    },

    onInputTab: function(input){
        SearchFlightController.nextInputFocus(input.attr('id'));
    },

    onInputClose: function(input){

        switch (input.attr('id')) {
            case "inputOrigin":
                $("label[for='inputDestination'], #inputDestinationIcon").show();
                if (mousedownOrigin) { return; }
            break;
            case "inputDestination":
                if (mousedownDestination) { return; }
            break;
            case "inputOriginMs2":
                $("label[for='inputDestinationMs2'], #inputDestinationIconMs2").show();
            break;
            default:
                break;
        }

        if( input.val() !== '' && (input.val().indexOf('(') === -1 && input.val().indexOf(')') === -1) ){
            SearchFlightController.executeBlurSuggestionBox(null, input, input.parent().find(".searchFlightTab ul"));
        }

        SearchFlightController.searchInputEfectOut(input);
        SearchFlightController.checkIfItsNationalFlightForCabin();

    },

    nextInputFocus: function(inputId){
        var next = null;
        switch(inputId){
            case 'inputOrigin':
                next = 'inputDestination';
            break;
            case 'inputOriginMs2':
                next = 'inputDestinationMs2';
            break;
            default:
            break;
        }
        $("body").click();
        if( next !== null ){
            setTimeout(function(){
                $("#"+next).focus();
            }, 100);
        }
    },

    defineAirportOrder: function(airport) {
        if (airport.name === 'Todos os Aeroportos'){
			return 1;
		} else if (airport.country === 'Brasil'){
			return 2;
		} else {
			return 3;
		}
    },

    callAirportSearch: function(text, inputSearch, callback) {
        var query = text;
        if (query) {
            query = `*${query.toUpperCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')}*`;
        }
    	$.ajax ({
            url: `${SearchFlightController.searchAirportURL}/v1/airports?size=50&q=description:${query}`,
            type: "GET",
            success: function(data) {
                const airportList = SearchFlightController.fillAirpotList(data);

                SearchFlightController.detectAirportIfExists(airportList, inputSearch);

            	callback();
            },
            error: function (jqXHR, exception) {
                SearchFlightController.msgLog("Erro: " + exception, "error");
                callback();
            }
        });
    },

    callAirportSearchIfExists: function(text, inputId, callback) {
    	$.ajax ({
            url: `${SearchFlightController.searchAirportURL}/v1/airports?size=50&q=description:${SearchFlightController.getAirportCode(text)}`,
            type: "GET",
            success: function(data) {
                const airportList = SearchFlightController.fillAirpotList(data);
                SearchFlightController.lastSearchAirports[inputId] = airportList;

            	callback();
            },
            error: function (jqXHR, exception) {
                SearchFlightController.msgLog("Erro: " + exception, "error");
                callback();
            }
        });
    },
    
    detectAirportIfExists : function(airportList, inputSearch) {
        // Identificadores dos campos origem e destino
        const oId = "inputOrigin";
        const dId = "inputDestination";
        const oM2Id = "inputOriginMs2";
        const dM2Id = "inputDestinationMs2";

        // Recupera valores dos campos origem e destino
        const o = $(`#${oId}`).val();
        const d = $(`#${dId}`).val();
        const oM2 = $(`#${oM2Id}`).val();
        const dM2 = $(`#${dM2Id}`).val();
        
        if (SearchFlightController.tripType !== "3") {
            SearchFlightController.lastSearchAirports[oM2Id] = [];
            SearchFlightController.lastSearchAirports[dM2Id] = [];   
        }
        
        if ((SearchFlightController.lastSearchAirports[oId] || SearchFlightController.lastSearchAirports[dId]) || (o && d)) {
            var currInput = inputSearch && inputSearch.attr('id');
    
            if (currInput === oId && d) {
                // Atuaiza lista de aeroportos a partir da origem, caso o destino ja esteja preenchido
                if (!SearchFlightController.lastSearchAirports[dId]) {
                    SearchFlightController.addAirpotListForCabin(d, dId, airportList, inputSearch, false);
                } else {
                    SearchFlightController.updateAirportListForCabin(airportList, inputSearch);
                }
            } else if (currInput === dId && o) { 
                // Atuaiza lista de aeroportos a partir do destino, caso a origem ja esteja preenchido
                if (!SearchFlightController.lastSearchAirports[oId]) {
                    SearchFlightController.addAirpotListForCabin(o, oId, airportList, inputSearch, false);
                } else {
                    SearchFlightController.updateAirportListForCabin(airportList, inputSearch);
                }
            } else if (currInput === oM2Id && dM2) { 
                // Atuaiza lista de aeroportos para multi-trechos a partir do destino, caso a origem ja esteja preenchido
                const searchIds = [oId, dId, dM2Id];
                var hasValueO = false;
                for (let i = 0; i < searchIds.length; i++) {
                    if (!SearchFlightController.lastSearchAirports[searchIds[i]]) {
                        const inputValue = $(`#${searchIds[i]}`).val();
                        const inputId = searchIds[i];

                        SearchFlightController.addAirpotListForCabin(inputValue, inputId, airportList, inputSearch, hasValueO);
                    }
                }
                
                if (!hasValueO) {
                    SearchFlightController.updateAirportListForCabin(airportList, inputSearch);
                }
            } else if (currInput === dM2Id && oM2) { 
                // Atuaiza lista de aeroportos a partir do destino, caso a origem ja esteja preenchido
                const searchIds = [oId, dId, oM2Id];
                var hasValueD = false;
                for (let i = 0; i < searchIds.length; i++) {
                    if (!SearchFlightController.lastSearchAirports[searchIds[i]]) {
                        const inputValue = $(`#${searchIds[i]}`).val();
                        const inputId = searchIds[i];

                        SearchFlightController.addAirpotListForCabin(inputValue, inputId, airportList, inputSearch, hasValueD);
                    }
                }

                if (!hasValueD) {
                    SearchFlightController.updateAirportListForCabin(airportList, inputSearch);
                }
            } else {
                SearchFlightController.updateAirportListForCabin(airportList, inputSearch);
            }
        } else {
            SearchFlightController.updateAirportListForCabin(airportList, inputSearch);
        }
    },

    addAirpotListForCabin : function(inputValue, inputId, airportList, inputSearch, hasValue) {
        clearTimeout(SearchFlightController.searchAirportsIfExists);
        
        SearchFlightController.searchAirportsIfExists = setTimeout(function() {
            // Realiza consulta da origem ja preenchida para atualizar a lista
            SearchFlightController.callAirportSearchIfExists(inputValue, inputId, function() {
                if (!hasValue) {
                    SearchFlightController.updateAirportListForCabin(airportList, inputSearch);
                }
                hasValue = true;
            });
        }, 150);
    },

    updateAirportListForCabin : function(airportList, inputSearch) {
        var newItens = [];
        for (var lastSearch in SearchFlightController.lastSearchAirports) {
            if (SearchFlightController.lastSearchAirports.hasOwnProperty(lastSearch)) {
                SearchFlightController.lastSearchAirports[lastSearch].forEach(function (element1) {
                    if (!airportList.find((element2) => element1.code === element2.code)) {
                        newItens.push(element1);
                    }
                });
            }
        }
        var lastSearchFullList = airportList.concat(newItens);
        var newListAirports = JSON.stringify(lastSearchFullList);

        if (airportList.length > 0 && inputSearch) {
            SearchFlightController.lastSearchAirports[inputSearch.attr('id')] = airportList;
        }

        SearchFlightController.listAirports = newListAirports;
        if (SearchFlightController.lsAvailable) {
            localStorage.setItem("airport-list", newListAirports);
    
            const airportsJsonOriginal = SearchFlightController.getAirports(newListAirports);
            const airportsJsonStrip = SearchFlightController.cleanCharacterSpecial(airportsJsonOriginal);
    
            SearchFlightController.airportsJsonOriginal = airportsJsonOriginal;
            SearchFlightController.airportsJsonStrip = airportsJsonStrip;
        }
    },

    airportDesc: function(airport) {
        var desc = airport.description;

        const commaCount = (desc.match(/,/g) || []).length;
        if (commaCount === 1) {
            desc = `${airport.city}, ${airport.country} (${airport.code}) [${airport.city}] `;
        } else if (commaCount === 2) {
            desc = `${airport.city}, ${airport.country}, ${airport.name} (${airport.code}) [${airport.city}] `;
        }

        return desc;
    },

    fillAirpotList : function(data) {
        const airportList = [];

        $.each(data, function(k, v) {
            airportList.push({
               city: v.city,
               code: v.code,
               congenere: v.congenere,
               country: v.country,
               g3: v.g3,
               name: v.name,
               order: SearchFlightController.defineAirportOrder(v),
               description: SearchFlightController.airportDesc(v)
           });
        });

        airportList.sort(function(a1, a2) {
            var order = a1.order - a2.order;
            if (order === 0) {
                order = (''+ a1.name).localeCompare(a2.name);
            }
            return order;
        });
        return airportList;
    },

