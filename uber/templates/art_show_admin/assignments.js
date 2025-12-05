var unsavedChanges;

function onBeforeUnload(e) {
    if (unsavedChanges === true) {
        e.preventDefault();
        e.returnValue = '';
        return;
    }

    delete e['returnValue'];
}

window.addEventListener('beforeunload', onBeforeUnload);

function get_query_variable(variable) {
    let rv = getQueryVariable(variable);
    return rv;
}
function set_query_variable(queryvars,push=false) {
    setQueryVariable(queryvars,push);
}

function getQueryVariable(variable) {
	/*
	
	Given a query variable, returns that variable's value.

	If the variable is undefined, returns undefined

	*/
	var query = window.location.search.substring(1);
	var vars = query.split("&");
	for (var i=0;i<vars.length;i++) {
		var pair = vars[i].split("=");
		if(pair[0] == variable) {
            if(pair.length==2) {
                return pair[1];
            }
            else {
                return true;
            }
        }
    }
	return(undefined); // If the queryvariable didn't exist.
}

function setQueryVariable(queryvars,push=false) {
    /*
    
    Given a dict, adds each value in the dict to the window path.

    If push is set to true, will push it to the history rather than use replaceState
    
    */

    var qv_text = "";

    if(queryvars!==undefined) {
        var qv_ids = Object.keys(queryvars);
        if(qv_ids.length>0) {
            qv_text = "?"+qv_ids[0]+"="+queryvars[qv_ids[0]];
            if(qv_ids.length>1) {
                for(var i=1;i<qv_ids.length;i++) {
                    qv_text = qv_text + "&" + qv_ids[i] + "=" + queryvars[qv_ids[i]];
                }
            }
        }
    }
    if(push==true) {
        window.history.pushState("Object","Title",window.location.pathname+qv_text);
    }
    else {
        window.history.replaceState("Object","Title",window.location.pathname+qv_text);
    }
}

function semirandom(offset,length) {
    /*
    length is the length of the string that should be returned
    offset is where it should start.
    */
    var pi_val = "3141592653589793238462643383279502884197169399375105820974944592307816406286208998628034825342117067982148086513282306647093844609550582231725359408128481117450284102701938521105559644622948954930381964428810975665933446128475648233786783165271201909145648566923460348610454326648213393607260249141273724587006606315588174881520920962829254091715364367892590360011330530548820466521384146951941511609433057270365759591953092186117381932611793105118548074462379962749567351885752724891227938183011949129833673362440656643086021394946395224737190702179860943702770539217176293176752384674818467669405132000568127145263560827785771342757789609173637178721468440901224953430146549585371050792279689258923542019956112129021960864034418159813629774771309960518707211349999998372978049951059731732816096318595024459455346908302642522308253344685035261931188171010003137838752886587533208381420617177669147303598253490428755468731159562863882353787593751957781857780532171226806613001927876611195909216420198938095257201065485863278865936153381827968230301952035301852968995773622599413891249721775283479131515574857242454150695950829533116861727855889075098381754637464939319255060400927701671139009848824012858361603563707660104710181942955596198946767837449448255379774726847104047534646208046684259069491293313677028989152104752162056966024058038150193511253382430035587640247496473263914199272604269922796782354781636009341721641219924586315030286182974555706749838505494588586926995690927210797509302955321165344987202755960236480665499119881834797753566369807426542527862551818417574672890977772793800081647060016145249192173217214772350141441973568548161361157352552133475741849468438523323907394143334547762416862518983569485562099219222184272550254256887671790494601653466804988627232791786085784383827967976681454100953883786360950680064225125205117392984896084128488626945604241965285022210661186306744278622039194945047123713786960956364371917287467764657573962413890865832645995813390478027590099465764078951269468398352595709825822620522489407726719478268482601476990902640136394437455305068203496252451749399651431429809190659250937221696461515709858387410597885959772975498930161753928468138268683868942774155991855925245953959431049972524680845987273644695848653836736222626099124608051243884390451244136549762780797715691435997700129616089441694868555848406353422072225828488648158456028506016842739452267467678895252138522549954666727823986456596116354886230577456498035593634568174324112515076069479451096596094025228879710893145669136867228748940560101503308";
    var pi_len = pi_val.length;

    length = parseInt(length);
    offset = parseInt(offset);
    var r_val = "" // value to be returned. Numeric string.
    if((offset+length) <= pi_len) {
        r_val = pi_val.substring(offset,offset+length);
    }
    else {
        if(offset >= pi_len) {
            // So in this case, the offset ITSELF is beyond the length of the request value, so we just loop around.
            var new_o = offset % pi_len;
            r_val = semirandom(new_o,length);
        }
        else {
            // This means that PART of the offset is within bounds.
            var delta_b = (offset+length) % pi_len;
            var part_a = pi_val.substring(offset,pi_len);
            var part_b = pi_val.substring(0,delta_b);
            r_val = part_a + "" + part_b;
        }
    }
    return r_val;
}

function semirandint(offset,a,b) {
    /*

    Returns a semirandom integer between values a and b inclusive

    */
    if(b===undefined) {
        // We were only passed two values, so return an integer between 0 and a, inclusive
        var b = parseInt(a);
        var a = 0;
    }
    var delta = parseInt(b+1)-parseInt(a);
    var rs = parseInt(parseFloat(delta)*parseFloat(semirandom(offset,3))/1000.0);
    return (parseInt(a)+rs);
}

function truncate(a,digits=1) {
    var fl_a = parseFloat(a);
    var exp = 10**digits;
    var rnd_a = parseFloat(parseInt(fl_a * exp))/exp;
    return rnd_a;
}

function unitconvert(val,src,as_string=false) {
    var converted = 0.0;
    var converted_str = "";
    if(src=="mi") {
        converted = parseFloat(val) * 1.6;
        converted_str = truncate(converted,1) + " km";
    }
    else if(src=="km") {
        converted = parseFloat(val)/1.6;
        converted_str = truncate(converted,1) + " mi";
    }
    if(as_string==true) {
        return converted_str;
    }
    else {
        return converted;
    }
}

class showMap {
    constructor(gridWidth, gridHeight) {
        this.panels = {};
        this.gridWidth = gridWidth;
        this.gridHeight = gridHeight;
        this.dx = 0; // left offset used for scrolling the map
        this.dy = 0; // top offset used for scrolling the map
        this.o_x;
        this.o_y;
        this.sel_a = false;
        this.sel_b = false;
        this.dots = false;
        this.zoom = 1;
        this.logic; // assignment logic controller.
        this.labels = false; // are labels being adjusted?
        this.face_ids = {}; // array of face_id : label
        this.face_names = {}; // array of label : face_id
        this.interactor;
        this.allocator;
    }

    createMap() {
        let m = this.gridWidth / this.gridHeight;
        if(m>1.0) {
            // Landscape
            this.displayWidth = $(document).width() * 0.7;
            this.displayHeight = ($(document).width() * 0.7) / m;
        }
        else {
            this.displayWidth = $(document).width()-300;
            this.displayHeight = (($(document).width()-300)*m);
        }
        this.o_x = this.displayWidth / (this.gridWidth+1);
        this.o_y = this.displayHeight / (this.gridHeight+1);
        let p = this.allocator.map_dom;
        let c = this.allocator.container_top;
        $(p).css({"width":this.displayWidth,"height":this.displayHeight});
        $(c).css({"height":this.displayHeight});
        this.addDots();
    }
    dotDraw() {
        if(this.dots === true) {
            this.hideDots();
        }
        else {
            this.showDots();
        }
    }
    addDots() {
        let m = this.gridWidth / this.gridHeight;
        $(".node_parent").remove();
        for(let x=1;x<=this.gridWidth;x++) {
            for(let y=1;y<=this.gridHeight;y++) {
                let dot_id = x + "_" + y;
                let pdot = $("<div />",{"class":"node_parent","css":{"left":x * this.o_x,"top":y * this.o_y},"attr":{"draggable":"false"}});
                let dot = $("<div />",{"class":"node","id":dot_id+"_dot","attr":{"node_id":dot_id,"draggable":"false"}});
                let ring = $("<div />",{"class":"node_ring","id":dot_id+"_ring","attr":{"node_id":dot_id,"draggable":"false"}});
                if(this.sel_a!==dot_id || this.sel_b!==dot_id) {
                    // If the dot is not CURRENTLY ACTIVE, then hide it.
                    $(ring).hide();
                } 
                let pmap = this;
                $(dot).on("click",{arg1:pmap,arg2:x,arg3:y},function(e){
                    e.data.arg1.activate(e.data.arg2,e.data.arg3);
                });
                $(pdot).append(dot);
                $(pdot).append(ring);
                if(this.dots===false) {
                    $(pdot).hide();
                }
                $(this.allocator.map_dom).append(pdot);
            }
        }
    }
    showDots() {
        this.dots = true;
        $(".node_parent").show();
        $(".panel_selector").show();
        $(".face_selector").hide();
        this.drawPanels();
    }
    hideDots() {
        this.dots = false;
        this.labels = false;
        // Clear selectors from the mouse logic handler
        this.sel_a = false;
        this.sel_b = false;
        this.interactor.reset();
        logic.shadeByUse();
        $(".node_parent").hide();
        $(".face_selector").show();
        $(".panel_selector").hide();
    }
    doLabels() {
        if(this.labels === false) {
            this.labels = true;
            this.logic.manual_assignee = "labels";
            this.logic.shadeByUse();
            $(".panel_selector").hide();
            $(".face_selector").show();
        }
        else {
            this.logic.manual_assignee = false;
            $(".panel_selector").show();
            $(".face_selector").hide();
            this.labels = false;
            this.drawPanels();
            this.logic.shadeByUse();
        }
    }
    makeLabel(face_id) {
        unsavedChanges = true;
        let ps = face_id.split("|")
        let p_id = ps[0]+"|"+ps[1];
        let p_dir = ps[2];
        let l_face = this.allocator.label["face"];
        let l_input = this.allocator.label["input"];
        $(l_face).html(face_id);
        if(this.panels[p_id].labels.hasOwnProperty(p_dir)) {
            $(l_input).val(this.panels[p_id].labels[p_dir]);
        }
        else {
            $(l_input).val("");
        }
    }
    applyLabel() {
        let l_face = this.allocator.label["face"];
        let l_input = this.allocator.label["input"];
        let ps = $(l_face).html().split("|")
        if(ps.length>0) {
            let p_id = ps[0]+"|"+ps[1];
            let p_dir = ps[2];
            let v = $(l_input).val();
            let f_id = p_id + "|" + p_dir; // reconstruct face ID, probably same as ps.html();
            this.face_ids[f_id] = v;
            this.face_names[v] = f_id;
            this.panels[p_id].labels[p_dir] = v;
        }
    }
    activate(x,y) {
        if(this.sel_a!==false) {
            // This means *a* node has been selected for A
            if(this.sel_a.x===x && this.sel_a.y===y) {
                // We are now unselecting this node.
                this.sel_a = false;
                $("#"+x+"_"+y+"_ring").hide();
            }
            else {
                // Hopefully node_b should be false.
                this.sel_b = {x:x,y:y};
                $("#"+x+"_"+y+"_ring").show();
                // Check to see if panels are horizontal.
                if(this.sel_b.y === this.sel_a.y) {
                    if(Math.abs(this.sel_b.x-this.sel_a.x)===1) {
                        // Simple case. Panels are horizontal and only one dot apart.
                        this.addPanel();
                    }
                    else {
                        let sx = parseInt(this.sel_a.x);
                        let fx = parseInt(this.sel_b.x);
                        let fy = parseInt(this.sel_a.y);
                        if(this.sel_b.x>this.sel_a.x) {
                            for(let i=sx;i<fx;i++) {
                                this.addPanel({x:i,y:fy},{x:i+1,y:fy});
                            }
                        }
                        else {
                            for(let i=sx-1;i>=fx;i--) {
                                this.addPanel({x:i,y:fy},{x:i+1,y:fy});
                            }
                        }
                    }
                    this.logic.setRecalculation(true);
                    this.drawPanels();
                }
                else if(this.sel_b.x === this.sel_a.x) {
                    // Panel is vertical.
                    if(Math.abs(this.sel_b.y-this.sel_a.y)===1) {
                        // Simple case. Panels are vertical and only one dot apart.
                        this.addPanel();
                    }
                    else {
                        let sy = parseInt(this.sel_a.y);
                        let fy = parseInt(this.sel_b.y);
                        let sx = parseInt(this.sel_a.x);
                        if(this.sel_b.y>this.sel_a.y) {
                            // Panel span is vertical, descending.
                            for(let i=sy;i<fy;i++) {
                                this.addPanel({x:sx,y:i},{x:sx,y:i+1});
                            }
                        }
                        else {
                            for(let i=sy;i>fy;i--) {
                                this.addPanel({x:sx,y:i-1},{x:sx,y:i});
                            }
                        }
                    }
                    this.logic.setRecalculation(true);
                    this.drawPanels();
                }
                else {
                    // Panels are not in the same plane.
                    // So just unset the selectors?
                    $("#"+parseInt(this.sel_a.x)+"_"+parseInt(this.sel_a.y)+"_ring").hide();
                    $("#"+parseInt(this.sel_b.x)+"_"+parseInt(this.sel_b.y)+"_ring").hide();
                    this.sel_a = false;
                    this.sel_b = false;
                }
                this.interactor.reset();
            }
        }
        else {
            this.sel_a = {x:x,y:y};
            $("#"+x+"_"+y+"_ring").show();
        }
    }
    addPanel(origin=false, terminus=false, usability=false, labels=false) {
        /*

        This creates a panel object and adds it to the map. The panel can be horizontal or vertical. The start and end coordinates MUST be either in the same horizontal or vertical plane.

        A panel ID is ALWAYS identified with the top-left coordinate first. This will be true EVEN IF THE START AND END ARE PROVIDED IN REVERSE ORDER. So a panel defined with its start and end as:

        Point A: {x:5,y:6}
        Point B: {x:6,y:6}
        = "5_6|6_6", but also

        Point A: {x:6,y:6}
        Point B: {x:5,y:6}
        = "5_6|6_6"

        For vertical panels:

        Point A: {x:3,y:4}
        Point B: {x:3,y:5}
        = "3_4|3_5", but also

        Point A: {x:3,y:5}
        Point B: {x:3,y:4}
        = "3_4|3_5"
        
        If it is prepopulated with a start and end coordinate (origin, terminus) it will use those. If not, it will take the sel_a and sel_b properties of the map object (which are the ones that have been selected by the user).

        Panels can be single or double-sided. The key is as follows:

        n: Panel allows art on neither side.
        b: Panel allows art on both sides.
        l,r: Vertical panel allowing art on the "left" or "right" side
        u,d: Horizontal panel allowing art on the "up" or "down" side

        labels defines an optional "label" component. This is used when the map is being preloaded.

        */
        unsavedChanges = true;
        let plm = {"a":{"h":"u","v":"l"},"b":{"h":"d","v":"r"}};
        let a = origin !== false ? origin : this.sel_a;
        let b = terminus !== false ? terminus : this.sel_b;
        let u = usability !== false ? usability : "b"; // Without any other context, create this as a both-sided panel.
        let l = {};
        let c;
        let p_m = this;
        let panel,panel_selector,panel_usage,p_id,face_selectoorigin,face_selectoterminus;
        if(a.x === b.x) {
            // Same x coordinate, so this must be a vertical panel
            c = "v";
            let p_a,p_b;
            l = labels !== false ? labels : {"l":"","r":""};
            if(a.y < b.y) {
                // a is further up than b.
                p_a = a;
                p_b = b;
            }
            else {
                p_a = b;
                p_b = a;
            }
            p_id = p_a.x + "_" + p_a.y + "|" + p_b.x + "_" + p_b.y;
            if(this.panels.hasOwnProperty(p_id)===false) {
                let usage_width = (this.o_x / 6.0);
                panel = $("<div />",{"class":"panel","id":p_id,"css":{"width":(this.o_x/16.0),"height":this.o_y},attr:{"draggable":"false"}});
                $(panel).css({"left":(p_a.x * this.o_x)-(this.o_x/32.0),"top":p_a.y * this.o_y});
                panel_selector = $("<div />",{"class":"panel_selector","id":p_id+"_selector","css":{"width":(this.o_x/3.0),"height":(this.o_y*0.8)},attr:{"draggable":"false"}});
                $(panel_selector).css({"left":(p_a.x * this.o_x)-(this.o_x/6.0),"top":(p_a.y * this.o_y)+(this.o_y*0.1)});

                face_selectoorigin = $("<div />",{"class":"face_selector","id":p_id+"|l_selector","css":{"width":(this.o_x/6.0),"height":(this.o_y*0.8)},attr:{"draggable":"false"}});
                $(face_selectoorigin).css({"left":(p_a.x * this.o_x)-(this.o_x/6.0),"top":(p_a.y * this.o_y)+(this.o_y*0.1)});
                $(face_selectoorigin).on("click",{arg1:p_id+"|l"},function(e) { logic.manualAssign(e.data.arg1)});
                

                face_selectoterminus = $("<div />",{"class":"face_selector","id":p_id+"|r_selector","css":{"width":(this.o_x/6.0),"height":(this.o_y*0.8)},attr:{"draggable":"false"}});
                $(face_selectoterminus).css({"left":(p_a.x * this.o_x)-(this.o_x*0.0),"top":(p_a.y * this.o_y)+(this.o_y*0.1)});
                $(face_selectoterminus).on("click",{arg1:p_id+"|r"},function(e) { logic.manualAssign(e.data.arg1)});

                $(panel_selector).on("click",{arg1:p_m,arg2:p_id},function(e){ e.data.arg1.changePanel(e.data.arg2)});
                panel_usage = $("<div />",{"class":"panel_usage","id":p_id+"_usage","css":{"width":(this.o_x/16.0),"height":this.o_y},attr:{"draggable":"false"}});
                $(panel_usage).css({"left":(p_a.x * this.o_x)-(this.o_x/32.0)-(usage_width-(this.o_y/64.0)),"top":p_a.y * this.o_y});
                //$(panel_usage).css({"left":(p_a.x * this.o_x)-(this.o_x/24.0+3.0),"top":p_a.y * this.o_y});
                $(panel_usage).css({"border-left-width":usage_width,"border-left-style":"solid","border-left-color":"var(--unused-border)"});
                $(panel_usage).css({"border-right-width":usage_width,"border-right-style":"solid","border-right-color":"var(--unused-border)"});
            }
        }
        else {
            if(a.y === b.y) {
                c = "h";
                let p_a,p_b;
                l = labels !==false ? labels : {"u":"","d":""};
                if(a.x < b.x) {
                    // a is further left than b.
                    p_a = a;
                    p_b = b;
                }
                else {
                    // b is further left than a, so we need to flip the point order.
                    p_a = b;
                    p_b = a;
                }
                p_id = p_a.x + "_" + p_a.y + "|" + p_b.x + "_" + p_b.y;
                if(this.panels.hasOwnProperty(p_id) === false) {
                    let usage_width = (this.o_y / 6.0);
                    panel = $("<div />",{"class":"panel","id":p_id,"css":{"width":this.o_x,"height":(this.o_y/16.0)}});
                    $(panel).css({"left":p_a.x * this.o_x,"top":(p_a.y * this.o_y)-(this.o_y/32.0)});
                    panel_selector = $("<div />",{"class":"panel_selector","id":p_id+"_selector","css":{"width":(this.o_x*0.8),"height":(this.o_y/3.0)}});
                    $(panel_selector).css({"left":(p_a.x * this.o_x)+(this.o_x*0.1),"top":(p_a.y * this.o_y)-(this.o_x/6.0)});

                    face_selectoorigin = $("<div />",{"class":"face_selector","id":p_id+"|u_selector","css":{"width":(this.o_x*0.8),"height":(this.o_y/6.0)}});
                    $(face_selectoorigin).css({"left":(p_a.x * this.o_x)+(this.o_x*0.1),"top":(p_a.y * this.o_y)-(this.o_x/6.0)});
                    $(face_selectoorigin).on("click",{arg1:p_id+"|u"},function(e) { logic.manualAssign(e.data.arg1)});

                    face_selectoterminus = $("<div />",{"class":"face_selector","id":p_id+"|d_selector","css":{"width":(this.o_x*0.8),"height":(this.o_y/6.0)}});
                    $(face_selectoterminus).css({"left":(p_a.x * this.o_x)+(this.o_x*0.1),"top":(p_a.y * this.o_y)-(this.o_x*0.0)});
                    $(face_selectoterminus).on("click",{arg1:p_id+"|d"},function(e) { logic.manualAssign(e.data.arg1)});

                    $(panel_selector).on("click",{arg1:p_m,arg2:p_id},function(e){ e.data.arg1.changePanel(e.data.arg2)});
                    panel_usage = $("<div />",{"class":"panel_usage","id":p_id+"_usage","css":{"width":this.o_x,"height":(this.o_y/16.0)}});
                    $(panel_usage).css({"left":p_a.x * this.o_x,"top":(p_a.y * this.o_y)-(this.o_y/32.0)-(usage_width-this.o_y/64.0)});
                    $(panel_usage).css({"border-top-width":usage_width,"border-top-style":"solid","border-top-color":"var(--unused-border)"});
                    $(panel_usage).css({"border-bottom-width":usage_width,"border-bottom-style":"solid","border-bottom-color":"var(--unused-border)"});
                }
            }
        }
        if(this.dots === false) {
            // The panel selector is used to change the side of the panel.
            // So if we are not in map-modifying mode (i.e. the dots are not visible) then hide this selector.
            $(panel_selector).hide();
        }

        // Hide the face selectors that will be used to manually assign artists.
        //$(face_selectoorigin).hide();
        //$(face_selectoterminus).hide();

        if(this.panels.hasOwnProperty(p_id)) {
            // Panel exists. So instead of adding it, delete it.
            $(this.panels[p_id].obj).remove();
            $(this.panels[p_id].use_obj).remove();
            $(this.panels[p_id].selector_obj).remove();
            $(this.panels[p_id].face_selectoorigin_obj).remove();
            $(this.panels[p_id].face_selectoterminus_obj).remove();

            // This should have been plm["a"][c] and plm["b"][c] (i.e. the direction marker (c) of point A and point B, but was instead plm[c]["a"] which did not exist.)

            let pla = this.panels[p_id].labels.hasOwnProperty(plm["a"][c]) ? this.panels[p_id].labels[plm["a"][c]] : "";
            let plb = this.panels[p_id].labels.hasOwnProperty(plm["b"][c]) ? this.panels[p_id].labels[plm["b"][c]] : "";
            
            if(pla!=="") {
                delete this.face_id[pla];
                delete this.face_names[p_id+"|"+plm["a"][c]];
            }
            if(plb!=="") {
                delete this.face_id[plb];
                delete this.face_names[p_id+"|"+plm["b"][c]];
            }
            delete this.panels[p_id];
        }
        else {
            this.panels[p_id] = {t:c,u:u,obj:panel,use_obj:panel_usage,selector_obj:panel_selector,face_selectoorigin_obj:face_selectoorigin,face_selectoterminus_obj:face_selectoterminus,labels:l};
            this.logic.created_sections.add(p_id);
            let ld = ["l","r","u","d"];
            for(let k in ld) {
                let ls = l.hasOwnProperty(ld[k]) ? l[ld[k]] : "";
                if(ls.length>0) {
                    // This implies that a label exists for this panel face.
                    this.face_ids[p_id+"|"+ld[k]] = ls;
                    this.face_names[ls] = p_id + "|" + ld[k];
                }
            }
            let show_map = this.allocator.map_dom;
            $(show_map).append(this.panels[p_id].obj);
            $(show_map).append(this.panels[p_id].use_obj);
            $(show_map).append(this.panels[p_id].selector_obj);
            $(show_map).append(this.panels[p_id].face_selectoorigin_obj);
            $(show_map).append(this.panels[p_id].face_selectoterminus_obj);
        }
        $("#"+a.x+"_"+a.y+"_ring").hide();
        $("#"+b.x+"_"+b.y+"_ring").hide();
        this.sel_a = false;
        this.sel_b = false;
    }
    drawPanels() {
        for(let k in this.panels) {
            let p = this.panels[k];
            let panel_usage = p.use_obj;
            if(p.t==="h") {
                // Horizontal panel.
                if(p.u==="n") {
                    // No borders should be declared here.
                    $(panel_usage).css({"border-top-color":"var(--unused-border)"});
                    $(panel_usage).css({"border-bottom-color":"var(--unused-border)"});
                }
                else {
                    if(p.u==="u") {
                        $(panel_usage).css({"border-top-color":"var(--available-border)"});
                        $(panel_usage).css({"border-bottom-color":"var(--unused-border)"});
                    }
                    if(p.u==="d") {
                        $(panel_usage).css({"border-top-color":"var(--unused-border)"});
                        $(panel_usage).css({"border-bottom-color":"var(--available-border)"});
                    }
                    if(p.u==="b") {
                        $(panel_usage).css({"border-top-color":"var(--available-border)"});
                        $(panel_usage).css({"border-bottom-color":"var(--available-border)"});
                    }
                }
            }
            else if(p.t==="v") {
                // Vertical panel.
                if(p.u==="n") {
                    // No borders should be declared here.
                    $(panel_usage).css({"border-right-color":"var(--unused-border)"});
                    $(panel_usage).css({"border-left-color":"var(--unused-border)"});
                }
                else {
                    if(p.u==="l") {
                        $(panel_usage).css({"border-left-color":"var(--available-border)"});
                        $(panel_usage).css({"border-right-color":"var(--unused-border)"});
                    }
                    if(p.u==="r") {
                        $(panel_usage).css({"border-left-color":"var(--unused-border)"});
                        $(panel_usage).css({"border-right-color":"var(--available-border)"});
                    }
                    if(p.u==="b") {
                        $(panel_usage).css({"border-left-color":"var(--available-border)"});
                        $(panel_usage).css({"border-right-color":"var(--available-border)"});
                    }
                }
            }
            
        }
    }
    changePanel(id) {
        // Changes the panel usage type.
        this.logic.setRecalculation(true);
        let next = {
            "h":{"n":"u","u":"d","d":"b","b":"n"},
            "v":{"n":"l","l":"r","r":"b","b":"n"}
        }
        if(this.panels.hasOwnProperty(id)) {
            let p = this.panels[id];
            p.u = next[p.t][p.u+""]; // Change the usage type to the next in the sequence.
        }
        this.drawPanels();
    }

    shiftMap() {

    }
}

class panelLogic {
    constructor() {
        this.map;
        this.sections = {};
        this.free_sections = {};
        this.created_sections = new Set();
        this.longest = {};
        this.panels = new Set();
        this.manual = new Set();
        this.faces = {}; // Map of face to section ID
        this.face_assignments = {}; // Map of face to artist name
        this.needs_recalculation = true;
        this.assignees = [];
        /*
            ["name_1",4],
            ["name_2",3],
            ["name_3",5],
            ["name_4",4],
            ["name_5",2],
            ["name_6",2],
            ["name_7",2],
            ["name_8",4],
            ["name_9",3],
            ["name_10",3],
            ["name_11",1],
            ["name_12",1],
            ["name_13",1],
            ["name_14",1],
            ["name_15",2],
            ["name_16",3],
            ["name_17",2],
            ["name_18",4],
            ["name_19",3],
            ["name_20",3],
            ["name_21",1],
            ["name_22",6],
            ["name_23",4],
            ["name_24",2],
            ["name_25",1],
            ["name_26",1],
            ["name_27",2],
            ["name_28",4],
            ["name_29",3],
            ["name_30",5],
            ["name_31",4],
            ["name_32",2],
            ["name_33",2],
            ["name_34",2],
            ["name_35",4],
            ["name_36",3],
            ["name_37",3],
            ["name_38",1],
            ["name_39",1],
            ["name_40",1],
            ["name_41",1],
            ["name_42",2],
        ];*/
        this.assigned = new Set();
        this.assignments = {};
    }

    artistList() {
        /*

        This ONLY creates the list of artists who need assignment.

        It also adds the click handlers to enter artist-assignment mode.

            */
        //console.log("artist list")
        let assigned_dom = this.map.allocator.artists["assigned"];
        let unassigned_dom = this.map.allocator.artists["unassigned"];
        $(assigned_dom).empty();
        $(unassigned_dom).empty();
        
        let unassigned = [];
        let assigned = [];
        let logic = this;
        for(let k in this.assignments) {
            let artist = this.assignments[k];
            let a_id = k;
            let artist_name = artist.name;
            let artist_assigned = artist.panels.size;
            let artist_unassigned = artist.needed - artist_assigned;
            if (artist_assigned > 0) {
                if(artist_assigned === 1) {
                    assigned.push([k,artist_name + " ("+artist_assigned+" {{ panels_or_tables }})"+artist.extra_info]);
                }
                else {
                    assigned.push([k,artist_name + " ("+artist_assigned+" {{ panels_or_tables }}s)"+artist.extra_info]);
                }
            }
            if (artist_unassigned>0) {
                if(artist_unassigned===1) {
                    unassigned.push([k,artist_name + " ("+artist_unassigned+" {{ panels_or_tables }})"+artist.extra_info]);
                }
                else {
                    unassigned.push([k,artist_name + " ("+artist_unassigned+" {{ panels_or_tables }}s)"+artist.extra_info]);
                }
            }
        }
        $(unassigned_dom).append("Artists needing assignment: ");
        let un_ul = $("<ul />");
        for(let k in unassigned) {
            let u_s = $("<span />",{id:unassigned[k][0]+"_u_key",text:unassigned[k][1]});
            if(this.manual_assignee===k[0]) {
                $(u_s).css({"font-weight":"bold"});
            }
            $(u_s).on("click",{arg1:logic,arg2:unassigned[k][0]},function(e) {
                e.data.arg1.setManualAssignee(e.data.arg2);
            })
            let u_li = $("<li />");
            $(u_li).append(u_s);
            $(un_ul).append(u_li);
        }
        $(unassigned_dom).append(un_ul);
        $(assigned_dom).append("Artists assigned: ");
        let a_ul = $("<ul />");
        
        for(let a in assigned) {
            let a_s = $("<span />",{id:assigned[a][0]+"_a_key",text:assigned[a][1]});
            if(this.manual_assignee===a[0]) {
                $(a_s).css({"font-weight":"bold"});
            }
            $(a_s).on("click",{arg1:logic,arg2:assigned[a][0]},function(e) {
                e.data.arg1.setManualAssignee(e.data.arg2);
                //e.data.arg1.shadeByUse(e.data.arg2);
            })
            let a_li = $("<li />");
            $(a_li).append(a_s);
            $(a_ul).append(a_li);
        }
        $(assigned_dom).append(a_ul);
    }
    shadeSection(id,type="section") {
        // Type could also be artist or face
        let rm = {
            "l":"border-left-color",
            "r":"border-right-color",
            "u":"border-top-color",
            "d":"border-bottom-color"
        }
        if(type === "section") {
            for(let s in this.sections) {
                for(let k of this.sections[s]) {
                    let ps = k.split("|");
                    let p_id = ps[0]+"|"+ps[1];
                    let rmid = ""+rm[ps[2]];
                    let kv = $(this.map.panels[p_id].use_obj);
                    if(s==id) {
                        $(kv).css(rmid,"var(--section-border)");
                    }
                    else {
                        $(kv).css(rmid,"var(--inner-border-color)");
                    }
                }
            }
            
        }
        else if(type === "face") {
            for(let s in this.faces) {
                let ps = s.split("|");
                let p_id = ps[0]+"|"+ps[1];
                let rmid = ""+rm[ps[2]];
                let kv = $(this.map.panels[p_id].use_obj);
                if(s === id) {
                    $(kv).css(rmid,"var(--section-border)");
                }
                else {
                    $(kv).css(rmid,"var(--inner-border-color)");
                }
            }
        } else {
            let pm = this.map;
            let ks = this.assignments[id]["panels"]; // This is a set of objects.
            ks.forEach((p) => {
                let ps = p.split("|");
                let p_id = ps[0]+"|"+ps[1];
                let rmid = ""+rm[ps[2]];
                let kv = $(pm.panels[p_id].use_obj);
                $(kv).css(rmid,"var(--selected-border)");
            })
        }
        
    }
    shadeByUse(artist_id=false) {
        //console.log("shade by use")
        this.face_assignments = {}; // Reset the face assignment chart.
        let rm = {
            "l":"border-left-color",
            "r":"border-right-color",
            "u":"border-top-color",
            "d":"border-bottom-color"
        }
        if(artist_id !== false) {
            // Manually shade the artist name in the key.
            $(this.map.allocator.artists.assigned).find("#"+artist_id+"_a_key").css({"font-weight":"bold"});
            $(this.map.allocator.artists.unassigned).find("#"+artist_id+"_u_key").css({"font-weight":"bold"});
        }
        let pm = this.map;
        for(let k in this.assignments) {
            let ks = this.assignments[k]["panels"]; // This is a set of objects.
            ks.forEach((p) => {
                this.face_assignments[p] = k;
                let ps = p.split("|");
                let p_id = ps[0]+"|"+ps[1];
                let rmid = ""+rm[ps[2]];
                if(pm.panels.hasOwnProperty(p_id)){
                    let kv = $(pm.panels[p_id].use_obj);
                    if(k===artist_id) {
                        $(kv).css(rmid,"var(--selected-artist)");
                        $(this.map.allocator.artists.assigned).find("#"+k+"_a_key").css({"font-weight":"bold"});
                        $(this.map.allocator.artists.unassigned).find("#"+k+"_u_key").css({"font-weight":"bold"});
                    }
                    else {
                        $(kv).css(rmid,"var(--selected-border)");
                        $(this.map.allocator.artists.assigned).find("#"+k+"_a_key").css({"font-weight":"normal"});
                        $(this.map.allocator.artists.unassigned).find("#"+k+"_u_key").css({"font-weight":"normal"});
                    }
                }
                
            })
        };
        for(let k in this.free_sections) {
            let ks = this.free_sections[k];
            ks.forEach((p) => {
                let ps = p.split("|");
                let p_id = ps[0]+"|"+ps[1];
                let rmid = ""+rm[ps[2]];
                if(pm.panels.hasOwnProperty(p_id)) {
                    let kv = $(pm.panels[p_id].use_obj);
                    $(kv).css(rmid,"var(--inner-border-color)");
                }
            });
        }
        for(let p_id of this.created_sections) {
            if(pm.panels.hasOwnProperty(p_id)) {
                let kv = $(pm.panels[p_id].use_obj);
                let rmid = pm.panels[p_id].u;
                if(rmid === "b") {
                    if(pm.panels[p_id].t==="v") {
                        // Vertical, so "b" means both left and right
                        $(kv).css("border-left-color","var(--created-border)");
                        $(kv).css("border-right-color","var(--created-border)");
                    }
                    else {
                        $(kv).css("border-top-color","var(--created-border)");
                        $(kv).css("border-bottom-color","var(--created-border)");
                    }
                }
                else if(rmid !== "n") {
                    rmid = rm[rmid];
                    $(kv).css(rmid,"var(--created-border)");
                }
            }
        }
    }
    resetPanels() {
        this.panels = new Set();
        this.sections = {};
    }
    assignAll() {
        unsavedChanges = true;
        this.assignees = this.assignees.sort((a,b) => { return a[1] < b[1];});
        for(let k of this.assignees) {
            if(this.assignments.hasOwnProperty(k[0])) {
                this.assignments[k[0]]["panels"] = new Set();
                for(let m_p of this.assignments[k[0]].manual) {
                    this.assignments[k[0]]["panels"].add(m_p);
                }
            }
            else {
                this.assignments[k[0]] = {"needed":k[1],"panels":new Set(),"manual":new Set()};
            }
        }
        this.free_sections = structuredClone(this.sections);
        let linear_space_required = 0;
        let linear_space_available = 0;
        for(let k of this.assignees) {
            linear_space_required += k[1];
        }
        for(let k in this.free_sections) {
            linear_space_available += this.sections[k].size;
        }
        for(let k in this.assignments) {
            let needed = this.assignments[k].needed - this.assignments[k].panels.size; // It's possible that there is already some necessary.
            let t = this.assign(needed,this.assignments[k].wide);
            if(t!==false) {
                // Check to see if there are already some assignments.
                if(this.assignments[k].panels.size>0) {
                    t.forEach((p) => {
                        this.assignments[k]["panels"].add(p);
                    })
                }
                else {
                    this.assignments[k]["panels"] = t;
                }
            }
        }
        this.artistList();
        this.shadeByUse();
    }

    assign(count,wide=false) {
        // Let's try to assign this.
        let artist_assignment = new Set();
        /*
        Test—try to find the biggest first?
        */
        let freesize = [];
        let exact = false;
        for(let k in this.free_sections) {
            if(this.free_sections[k].size>0 && exact === false) {
                if(this.free_sections[k].size==count) {
                    // Let's try to fill the first available one of EXACTLY the right size.

                    // Check to see if we need this to be be wide.
                    if(wide!==false) {
                        if(logic.checkMaxLinear(this.free_sections[k])>=parseInt(wide)) {
                            // So this fits a wide description.
                            exact = k;
                        }
                    }
                }
                freesize.push({key:k,size:this.free_sections[k].size});
            }
        }
        if(exact!==false) {
            let s = this.free_sections[exact];
            s.forEach((panel) => {
                if(artist_assignment.size<count) {
                    artist_assignment.add(panel);
                    s.delete(panel);
                }
            });
        }
        else {
            // No exact match, sort through to find the one with the most free space afterwards.
            freesize = freesize.sort((a,b) => { return a.size > b.size;});
            for(let k_f in freesize) {
                let k = freesize[k_f].key;
                if(this.free_sections[k].size<count) {
                    //console.log("This section is too small: "+k);
                }
                else {
                    //Test: Try to find the FIRST available slot.
                    if(wide===false) {
                        // If we don't have to check for width, then the assignment process is easy.
                        while(artist_assignment.size<count) {
                            let s = this.free_sections[k];
                            s.forEach((panel) => {
                                if(artist_assignment.size<count) {
                                    artist_assignment.add(panel);
                                    s.delete(panel);
                                }
                            });
                        }
                    }
                    else {
                        // we need to find a wide space within a block of panels.
                        if(artist_assignment.size<count) {
                            // Still have panels to assign.
                            let s = this.free_sections[k];
                            let sz = s.size; // This is the size of the set.
                            let o = 0; // Offset within set.
                            let match = false;
                            let opts = {};
                            s.forEach((p) => {
                                if(o<(sz-count)) {
                                    if(opts.hasOwnProperty(o)) { 
                                        opts[o].add(p);
                                    }
                                    else { 
                                        opts[o] = new Set([p])
                                    }
                                }
                                for(let k in opts) {
                                    if(opts[k].size<count) {
                                        opts[k].add(p);
                                    }
                                }
                                o++;
                            });
                            // Naive initial implementation.
                            // We will just take the FIRST block that is valid.

                            for(let k in opts) {
                                if(match===false) {
                                    if(this.checkMaxLinear(opts[k])>=wide) {
                                        // This means this BLOCK is acceptable.
                                        match = true;
                                        let set_left = new Set();
                                        let set_right = new Set();
                                        let set_off = 0;
                                        s.forEach((p) => {
                                            if(opts[k].has(p)) {
                                                // So this is one of the panels we want to assign.
                                                artist_assignment.add(p);
                                                s.delete(p);
                                            }
                                            else {
                                                if(set_off<=parseInt(k)) {
                                                    // This ID within the set is less than the offset.
                                                    // Which means we are in a part of the set BEFORE the offset.
                                                    set_left.add(p);
                                                    s.delete(p);
                                                }
                                                else {
                                                    set_right.add(p);
                                                    s.delete(p);
                                                }
                                            }
                                        });
                                        let cf = Object.keys(this.free_sections).length;
                                        this.free_sections[cf] = set_left;
                                        this.free_sections[cf+1] = set_right;
                                    }
                                }
                            }
                        }
                    }
                    
                }
            }
        }
        
        if(artist_assignment.size!=0) {
            return artist_assignment;
        }
        else {
            // This implies there was a problem in assigning the artist.
            return false;
        }
    }
    
    clearAssignment(name="none") {
        let target = this.assignments.hasOwnProperty(name) ? this.assignments[name] : false;
        if(target===false) {
            return;
        }
        let freed_panels = new Set();
        for(let k of target.panels) {
            freed_panels.add(k);
            target.panels.delete(k);
        }
        for(let k of target.manual) {
            freed_panels.add(k);
            target.manual.delete(k);
        }
        for(let k of freed_panels) {
            if(this.manual.has(k)) {
                this.needs_recalculation = true;
                this.manual.delete(k);
            }
            this.free_sections[Object.keys(this.free_sections).length] = [k];
        }
        this.artistList();
        this.shadeByUse(name);
    } 

    assign_old(count) {
        // Let's try to assign this.
        let artist_assignment = new Set();
        /*
        Test—try to find the biggest first?
        */
        let freesize = [];
        for(let k in this.free_sections) {
            if(this.free_sections[k].size>0) {
                freesize.push({key:k,size:this.free_sections[k].size});
            }
        }
        freesize = freesize.sort((a,b) => { return a.size > b.size;});
        for(let k in this.free_sections) {
            if(this.free_sections[k].size<count) {
                //console.log("This section is too small: "+k);
            }
            else {
                //Test: Try to find the FIRST available slot.
                while(artist_assignment.size<count) {
                    let s = this.free_sections[k];
                    s.forEach((panel) => {
                        
                        if(artist_assignment.size<count) {
                            artist_assignment.add(panel);
                            s.delete(panel);
                        }

                    });
                }
            }
        }
        if(artist_assignment.size!=0) {
            return artist_assignment;
        }
        else {
            // This implies there was a problem in assigning the artist.
            return false;
        }
    }
    manualAssign(face_id) {
        /*
        This will set a special mode that lets us assign panels directly to an artist.
        */
        //console.log("manual assign")
        unsavedChanges = true;
        let single_button = this.map.allocator.buttons["assign_single"];
        this.map.allocator.assignmentVisibility();
        let has_assignee = this.hasOwnProperty("manual_assignee") ? this.manual_assignee : false;
        if(has_assignee === "labels") {
            this.shadeSection(face_id, "face");
            this.map.makeLabel(face_id);
            return;
        }
        else if(has_assignee === false) {
            if(this.face_assignments.hasOwnProperty(face_id)) {
                this.setManualAssignee(this.face_assignments[face_id]);
            }
            return;
        }
        else {
            // Case where a manual assignee EXISTS but we want to choose another one
            if(this.map.interactor.shift===true) {
                if(this.face_assignments.hasOwnProperty(face_id)) {
                    this.setManualAssignee(this.face_assignments[face_id]);
                }
            return;
            }
            
        }
        if(this.faces.hasOwnProperty(face_id)) {
            // This implies that it is a valid panel face.
            let man = this.assignments[this.manual_assignee];
            if(man.panels.size>=man.needed) {
                $(single_button).html("Finish Assigning");
                return;
            }
            if(man.panels.has(face_id)) {
                // This face ID is currently assigned to the artist.
                this.manual.delete(face_id);
                man.panels.delete(face_id);
                man.manual.delete(face_id);
                this.free_sections[this.faces[face_id]].add(face_id);
            }
            else {
                // This face ID is not currently assigned to the artist.
                if(this.manual.has(face_id)===false) {
                    // It is also not a face_id that has already been assigned in general.
                    // So now it should be assigned.
                    this.manual.add(face_id);
                    man.panels.add(face_id);
                    if(man.hasOwnProperty("manual")) {
                        man.manual.add(face_id);
                    }
                    else {
                        man.manual = new Set([face_id]);
                    }
                    this.free_sections[this.faces[face_id]].delete(face_id);
                }
            }
            /*
            if(this.assignments[this.manual_assignee].panels.size>0) {
                //this.assignments[this.manual_assignee].manual = new Set(this.assignments[this.manual_assignee]["panels"]);
                $(single_button).html(this.getManualAssigneeLabel(this.manual_assignee));
            }
            else {
                //this.assignments[this.manual_assignee].manual = new Set();
                man.manual = new Set();
                
            }
            */
            $(single_button).html(this.getManualAssigneeLabel(this.manual_assignee));
            if(this.manual.size>0) {
                this.setRecalculation(true);
            }
            else {
                this.setRecalculation(false);
            }
            this.artistList();
        }
        else if (this.manual.has(face_id)) {
            if(this.assignments[this.manual_assignee].panels.has(face_id)) {
                // This face ID is currently assigned to the artist.
                this.manual.delete(face_id);
                this.assignments[this.manual_assignee].panels.delete(face_id);
                this.assignments[this.manual_assignee].manual.delete(face_id);
                this.free_sections[Object.keys(this.free_sections).length] = new Set([face_id]);
                $(single_button).html(this.getManualAssigneeLabel(this.manual_assignee));
                this.setRecalculation(true);
                this.artistList();
                //this.free_sections[this.faces[face_id]].add(face_id);
            }
        }
        else {
            console.log("Not a valid face.");
        }
        this.shadeByUse(this.manual_assignee);
    }
    getManualAssigneeLabel(artist_id) {
        let label = "Assigning Artist: "+artist_id;
        if(this.assignments.hasOwnProperty(artist_id)) {
            label = "Assigning Artist: "+this.assignments[artist_id].name;
            if(this.assignments[artist_id].panels.size > 0) {
                // Show that you can stop assigning before all panels are done
                label = "Finish Assigning";
            }
        }
        return label;
    }
    setManualAssignee(artist_id) {
        let single_button = map.allocator.buttons["assign_single"];
        let assign_button = map.allocator.buttons["assign"];
        let unassigned_dom = map.allocator.artists["unassigned"];
        let assigned_dom = map.allocator.artists["assigned"];
        if(this.manual_assignee===artist_id) {
            // Click to exit assignment.
            this.manual_assignee = false;
            // Unbold everyone in the unassigned list.
            $(unassigned_dom).children("ul").children("li").each(function() { $(this).children("span").css("font-weight","")});
            //$(single_button).hide();
            //$(assign_button).show();
            //$(".face_selector").hide();
        }
        else {
            this.manual_assignee = artist_id;
            $(single_button).html(this.getManualAssigneeLabel(artist_id));
            // Unbold everyone in the unassigned list.
            $(unassigned_dom).children("ul").children("li").each(function() { $(this).children("span").css("font-weight","")});
            
            //$(single_button).show();
            //$(assign_button).hide();
            //$(".face_selector").show();
        }
        //console.log("set manual assignee")
        map.allocator.assignmentVisibility();
        this.shadeByUse(this.manual_assignee);
    }
    async buildSections(first_run=false) {
        if (first_run !== true) {
            for(let k of this.assignees) {
                if(this.assignments.hasOwnProperty(k[0])) {
                    if(this.assignments[k[0]].manual.size === 0) {
                        // if manual was true then don't automatically remove this from calculation.
                        this.assignments[k[0]].panels = new Set();
                    }
                } else {
                    this.assignments[k[0]] = {"needed": k[1], "panels": new Set(), "manual": false};
                }
                
            }
        }
        this.assigned = new Set();
        this.created_sections = new Set();
        let built = await this.decomposeAll();
        if(built === true) {
            let resolved = await this.resolveLongest();
            if(resolved === true) {
                this.setRecalculation(false);
                this.free_sections = structuredClone(this.sections);
                if (first_run === true) {
                    let all_assignments = new Set();
                    for(let id in this.assignments) {
                        this.assignments[id]['panels'].forEach(item => all_assignments.add(item));
                        this.assignments[id]['manual'].forEach(item => all_assignments.add(item));
                    }
                    for(let id in this.free_sections) {
                        this.free_sections[id] = this.free_sections[id].difference(all_assignments);
                    }
                    unsavedChanges = false;
                }
                this.artistList();
                this.shadeByUse();
            }
        }
        this.setRecalculation(false);
        //console.log("build sections")
        this.map.allocator.assignmentVisibility();        
        return true;
    }
    async decomposeAll() {
        this.longest = {};
        this.sections = {};
        for(let k in this.map.panels) {
            this.decompose(k);
        }
        return true;
    }
    async decompose(p_id, dir) {
        let segment_finish = false;

        let p = this.map.panels[p_id];
        let v = {
            "h":["u","d"],
            "v":["l","r"]
        }
        for(let d of v[p.t]) {
            let ck_id = p_id + "";
            let ck_dir = d;
            if(p.u===d || p.u==="b") {
                // Check to see if we should evaluate these options.
                segment_finish = false;
                if(this.panels.has(ck_id+"|"+d)===false && this.manual.has(ck_id+"|"+d)===false) {
                    let next_id = Object.keys(this.sections).length;
                    this.sections[next_id] = [p_id+"|"+ck_dir];
                    let build_segments = new Set();
                    while(segment_finish===false) {
                        let v = this.checkAdjacency(ck_id,ck_dir);
                        if(v===false) {
                            let adj_id = ck_id+"|"+ck_dir;
                            this.panels.add(adj_id);
                            segment_finish = true;
                        }
                        else {
                            let adj_id = ck_id+"|"+ck_dir;
                            this.panels.add(adj_id);
                            ck_id = v[0]+"";
                            this.sections[next_id].push(v[0]+"|"+v[1]);
                            // Confirm that we've checked this option.
                            ck_dir = v[1]+"";
                        }
                    }
                    for(let k of this.panels) {
                        if(this.longest.hasOwnProperty(k)) {
                            if(this.sections[next_id].length>this.longest[k][1]) {
                                this.longest[k] = [next_id,this.sections[next_id].length];
                            }
                        }
                        else {
                            this.longest[k] = [next_id,this.sections[next_id].length];
                        }
                    }
                    this.panels = new Set();
                }
            }
        }
        return true;
    }
    async resolveLongest() {
        $("#section_list").empty();
        this.faces = {};
        let new_sections = structuredClone(this.sections);
        //this.sections = {};
        let used_sections = new Set();
        for(let k in this.longest) {
            used_sections.add(this.longest[k][0]);
        }
        this.sections = {};
        for(let k of used_sections) {
            let new_id = Object.keys(this.sections).length;
            this.sections[new_id] = new Set();
            for(let p of new_sections[k]) {
                this.sections[new_id].add(p);
                this.faces[p] = new_id; // Add which section this belongs to.
            }
            let s_select = $("<div />",{"class":"section_selector","text":new_id});
            $(s_select).on("click",{arg1:new_id},function(e) {
                logic.shadeSection(e.data.arg1);
            });
            //$("#section_list").append(s_select);
            //this.sections[new_id] = new_sections[k];
        }
        return true;
    }
    checkAdjacency(p_id,face) {
        let p = this.map.panels[p_id];
        /*

        Adjacencies:

        p is a HORIZONTAL panel indexed at x1_y1|x2_y1
            if p has a TOP:
                p could be adjacent to x2_y(1-2)|x2_y1 if x2_y(1-2)|x2_y1 has a LEFT
                else:
                    p could be adjacent to x2_y1|x(2+1)_y1 if x2_y1|x(2+1)_y1 has a TOP
                    else:
                        p could be adjacent to (x1-1)_y1|x1_y1 if (x1-1)_y1|x1_y1 has a TOP
                        else:
                            link TERMINATE
            if p has a BOTTOM:
                p could be adjacent to x2_y1|x2_y(1+1) if x2_y1|x2_y(1+1) has a LEFT
                else:
                    p could be adjacent to x2_y1|x(2+1)_y1 if x2_y1|x(2+1)_y1 has a BOTTOM
                    else:
                        link TERMINATE


        p is a VERTICAL panel indexed at x1_y1|x1_y2
            if p has a LEFT:
                p could be adjacent to (x1-1)_y1|x1_y1 if (x1-1)_y1|x1_y1 has a BOTTOM
        */
        let p_o = p_id.split("|");
        let p_a = {x:parseInt(p_o[0].split("_")[0]),y:parseInt(p_o[0].split("_")[1])};
        let p_b = {x:parseInt(p_o[1].split("_")[0]),y:parseInt(p_o[1].split("_")[1])};
        let valid_adjacency = false;
        let opts = [];
        if(face==="u") {
            // Adjacency check request is for adjacencies to the top face.
            opts.push([p_a.x+"_"+(p_a.y-1)+"|"+p_a.x+"_"+p_a.y,"|r","r"]); // up, right
            opts.push([p_b.x+"_"+(p_b.y-1)+"|"+p_b.x+"_"+p_b.y,"|l","l"]); // up, left
            opts.push([p_b.x+"_"+p_b.y+"|"+(p_b.x+1)+"_"+p_b.y,"|u","u",p_b.x+"_"+(p_b.y-1)+"|"+(p_b.x)+"_"+(p_b.y)]); // level, right
            opts.push([(p_a.x-1)+"_"+p_a.y+"|"+p_a.x+"_"+p_a.y,"|u","u",p_a.x+"_"+(p_a.y-1)+"|"+(p_a.x)+"_"+(p_a.y)]); // level, left
        }
        else if(face==="d") {
            // Adjacency check request is for adjacencies to the bottom face.
            opts.push([p_a.x+"_"+(p_a.y)+"|"+p_a.x+"_"+(p_a.y+1),"|r","r"]); // down, right
            opts.push([p_b.x+"_"+(p_b.y)+"|"+p_b.x+"_"+(p_b.y+1),"|l","l"]); // down, left
            opts.push([p_b.x+"_"+p_b.y+"|"+(p_b.x+1)+"_"+p_b.y,"|d","d",p_b.x+"_"+p_b.y+"|"+(p_b.x)+"_"+(p_b.y+1)]); // level, right
            opts.push([(p_a.x-1)+"_"+p_a.y+"|"+p_a.x+"_"+p_a.y,"|d","d",p_a.x+"_"+p_a.y+"|"+(p_a.x)+"_"+(p_a.y+1)]); // level, left
        }
        else if(face==="l") {
            opts.push([(p_a.x-1)+"_"+p_b.y+"|"+p_a.x+"_"+p_b.y,"|u","u"]); // panel down-left has an upper face
            opts.push([(p_a.x-1)+"_"+p_a.y+"|"+p_a.x+"_"+p_a.y,"|d","d"]); // panel up-left has a lower face
            opts.push([p_a.x+"_"+(p_a.y-1)+"|"+p_a.x+"_"+p_a.y,"|l","l",(p_a.x-1)+"_"+p_a.y+"|"+p_a.x+"_"+p_a.y]); // panel up has a left face
            opts.push([p_a.x+"_"+(p_b.y)+"|"+p_a.x+"_"+(p_b.y+1),"|l","l",(p_b.x-1)+"_"+p_b.y+"|"+p_b.x+"_"+p_b.y]); // panel down has a left face
        }
        else if(face==="r") {
            opts.push([(p_a.x)+"_"+p_b.y+"|"+(p_a.x+1)+"_"+p_b.y,"|u","u"]); // panel down-right has an upper face
            opts.push([(p_a.x)+"_"+p_a.y+"|"+(p_a.x+1)+"_"+p_a.y,"|d","d"]); // panel up-right has a lower face
            opts.push([p_a.x+"_"+(p_a.y-1)+"|"+p_a.x+"_"+p_a.y,"|r","r",(p_a.x)+"_"+p_a.y+"|"+(p_a.x+1)+"_"+p_a.y]); // panel up has a right face
            opts.push([p_a.x+"_"+(p_b.y)+"|"+p_a.x+"_"+(p_b.y+1),"|r","r",(p_b.x)+"_"+p_b.y+"|"+(p_b.x+1)+"_"+p_b.y]); // panel down has a right face
        }
        for(let o of opts) {
            let o_valid = (this.map.panels.hasOwnProperty(o[0]) && this.panels.has(o[0]+o[1])===false) ? true : false;
            if(o_valid===true) {
                // Worth checking the adjacencies of the next value.
                let o_p = this.map.panels[o[0]]; // this is the map panel.
                let cross = false;
                if(o.length===4) {
                    if(this.map.hasOwnProperty(o[3])!==false) { cross =true; }
                }
                if(cross===false) {
                    // There is no possible crossing panel we need to avoid on this level.
                    if(this.map.panels.hasOwnProperty(o[3])===false) {
                        if(o_p.u===o[2] || o_p.u==="b") { // So this is a valid match.
                            if(this.manual.has(o[0]+"|"+o[2])===false) {
                                // This means it is also not a manually blocked node.
                                valid_adjacency = [o[0],o[2]];
                            }
                        }
                    }
                }
            }
        }                   
        return valid_adjacency;
        
    }
    checkMaxLinear(prng) {
        /*
        prng can be a set or an array of panels.
        */
        let pl = [];
        if(Array.isArray(prng)===true) {
            for(let k in prng) {
                pl.push(prng[k]);
            }
        }
        else {
            prng.forEach((p) => { pl.push(p)});
        }
        let last_dir;
        let check_lin = 0;
        let max_lin = 0;
        for(let k in pl) {
            let check_dir = pl[k].split("|")[2];
            if(check_dir!==last_dir) {
                // Reset counter
                if(check_lin>=max_lin) {
                    max_lin = parseInt(check_lin);
                }
                last_dir = check_dir;
                check_lin = 1;
            }
            else {
                check_lin++;
                if(check_lin>=max_lin) {
                    max_lin = parseInt(check_lin);
                }
            }
        }
        return max_lin;
    }
    setRecalculation(recalculate=false) {
        this.needs_recalculation = recalculate;
        if(recalculate===false ) {
            // No longer need recalculating. Hide the recalculate marker.
            if(this.map.dots===true) {
                this.map.allocator.buttons["modify"].html("Done Modifying");
            }
            else {
                this.map.allocator.buttons["modify"].html("Modify Layout");
            }
        }
        else {
            if(this.map.dots===true) {
                this.map.allocator.buttons["modify"].html("Done Modifying (will require recalculation)");
            }
            else {
                this.map.allocator.buttons["modify"].html("Modify Layout");
            }
        }
    }
}

class serialize {
    constructor(args) {
        this.parent = args.hasOwnProperty("parent") ? args.parent : false;
        this.parent_type = args.hasOwnProperty("type") ? args.type : false;
        this.source = {"layout":"#layout_predef","artist":this.parent.map.allocator.load_src};
        this.deserializer = args.hasOwnProperty("deserializer") ? args.deserializer : false;
        this.input = false;
        if (this.deserializer !== false) {
            $(this.deserializer).on("click",{arg1:this},function(e) {
                e.data.arg1.deserialize();
                if(e.data.arg1.parent_type === "artist") {
                    e.data.arg1.parent.buildSections();
                }
            })
        }
        else {
            this.deserializer = this.parent.map.allocator.buttons["load"];
            /*
            $(this.deserializer).on("click",{arg1:this},function(e) {
                e.data.arg1.deserialize();
                if(e.data.arg1.parent_type==="artist") {
                    e.data.arg1.parent.buildSections();
                }
            });
            */
        }
    }

    async deserialize(data="self") {
        /*
        Self: Data stored on page.
        */
        let src; // We want this to be some kind of a list or array
        if(data === "self") {
            let src_html = $(this.source[this.parent_type]).val();
            src_html = src_html.replace(/[\n\r,]+/gi,"⬛");
            let src_arr = src_html.split("⬛");
            src = [];
            for(let k in src_arr) {
                let kp = this.parse(src_arr[k]);
                if(kp !== false) {
                    src.push(kp);
                }
            }
        }
        let loaded = await this.load(src);
        return loaded;
    }

    async deserializeCSV() {
        if(this.input===false) {
            // No file input type declared for this.
            return;
        }
        let reader = new FileReader();
        const parent = this;
        reader.onload = () => { parent.parseCSV(reader.result); }
        reader.readAsText(this.input[0].files[0]);
        return true;
    }
    async parseCSV(raw_data) {
        let csv_raw = raw_data.split(/[\n\r]/);
        let csv_vals = [];
        let csv_string = [];
        for(let i=1;i<csv_raw.length;i++) {
            let subvals = csv_raw[i].split(",");
            if(subvals.length>1) {
                let new_val = [];
                new_val.push(subvals[0]);
                new_val.push(parseInt(subvals[1]));
                if(subvals.length>2) {
                    if(subvals[2]!=="") {
                        // This means the artist might have a wide panel.
                        new_val.push("wide|"+subvals[2]);
                    }
                }
                csv_vals.push(new_val);
                csv_string.push(new_val.join("•"));
            }
        }
        $(this.source[this.parent_type]).html(csv_string.join("\n"));
        let loaded = await this.load(csv_vals);
        return loaded;
    }

    serialize(data="self", extended=false) {
        let src;
        let panel_layout = {};

        if(this.parent_type === "layout" || data === "server") {
            for(let p in this.parent.map.panels) {
                panel_layout[p] = {
                    "t":this.parent.map.panels[p].t,
                    "u":this.parent.map.panels[p].u,
                    "labels":structuredClone(this.parent.map.panels[p].labels)
                }
            }
        }

        if(data === "self") {
            if(this.parent_type === "artist") {
                $(this.source[this.parent_type]).value = ""; // Delete the load box.
                let allArtists = [];

                for(let id in this.parent.assignments) {
                    let artistInfo = this.parent.assignments[id];

                    // Build array
                    let artistArray = [id, artistInfo.name, artistInfo.needed]

                    if(extended === true) {
                        // If Artist is extended, we want to also include the manual def panels.
                        artistInfo.panels.forEach((p) => {
                            artistArray.push(p);
                        });
                    }
                    if(this.parent.assignments[id].wide !== false) {
                        artistArray.push("wide|"+this.parent.assignments[id].wide);
                    }
                    allArtists.push(artistArray.join("•"));
                }
                $(this.source[this.parent_type]).val(allArtists.join("\n"));
            }
            else if(this.parent_type === "layout") {
                let panel_layout = {};
                for(let p in this.parent.map.panels) {
                    panel_layout[p] = {
                        "t":this.parent.map.panels[p].t,
                        "u":this.parent.map.panels[p].u,
                        "labels":structuredClone(this.parent.map.panels[p].labels)
                    }
                }
                let download_el = document.createElement("a");
                download_el.setAttribute("href","data:text/plain;charset=utf-8,"+encodeURIComponent(JSON.stringify(panel_layout)));
                download_el.setAttribute("download","layout.json");
                document.body.appendChild(download_el);
                download_el.click();
                document.body.removeChild(download_el);
            }
        }
        else if(data == "server") {
            unsavedChanges = false;
            let serializableArtists = structuredClone(this.parent.assignments);
            for(let id in this.parent.assignments) {
                serializableArtists[id]['panels'] = Array.from(this.parent.assignments[id]['panels'])
                serializableArtists[id]['manual'] = Array.from(this.parent.assignments[id]['manual'])
            }
            
            $.ajax({
                method: 'POST',
                url: 'save_map',
                dataType: 'json',
                data: {
                    gallery: {{ gallery }},
                    surface_type: {{ surface_type }},
                    csrf_token: csrf_token,
                    panels: JSON.stringify(panel_layout),
                    assignments: JSON.stringify(serializableArtists),
                },
                success: function (json) {
                    hideMessageBox();
                    var message = json.message;
                    if (json.success) {
                    $("#message-alert").addClass("alert-info").show().children('span').html(message);
                    window.scrollTo(0,0); setTimeout(() => { window.scrollTo(0, 0); }, 100);
                    } else {
                    showErrorMessage(message);
                    }
                },
                error: function () {
                    showErrorMessage('Unable to connect to server, please try again.');
                }
                });
        }

    }

    async load(src) {
        if(this.parent_type === "artist") {
            // First we need to clear the existing artist list.
            this.parent.assignees = [];
            this.parent.assignments = {};
            for(let index in src) {
                let artistInfo = src[index];
                let as_obj = {0: artistInfo[0], 1: artistInfo[2]}
                this.parent.assignees.push(as_obj);
                let panelArr = [];
                let is_wide = false;
                if(artistInfo.length > 3) {
                    for(let i=3; i<artistInfo.length; i++) {
                        // Additional panels
                        if(artistInfo[i].substring(0,4) === "wide") {
                            // This is not a panel definition, it's a declaration the artist has art that needs adjacent panels.
                            let ws = artistInfo[i].split("|")
                            is_wide = parseInt(ws[1]);
                        }
                        else {
                            this.parent.manual.add(artistInfo[i]);
                            panelArr.push(artistInfo[i]);
                        }
                    }
                }
                this.parent.assignments[artistInfo[0]] = {"name": artistInfo[1], "needed": artistInfo[2],
                    "panels": new Set(panelArr), "manual": new Set(panelArr), "wide": is_wide};
                
            }
            this.parent.artistList();
        }
        return true;
    }

    parse(r_i) {
        /*
        Takes a string and returns the parsed element
        */
        let item = r_i.trim();
        let wf = item.length > 0 ? item.substring(0,1) : false;
        if(wf!==false) {
            if(wf==="#") {
                // This is a comment string, in other words.
                // Return false.
                return false;
            }
        }
        else {
            // Empty string, return false.
            return false;
        }
        let item_obj;
        if(this.parent_type === "artist") {
            let inputStr = item.trim();
            if(inputStr.length > 0) {
                // Input string has to be longer than 1
                let inputArr = inputStr.split("•");
                let id = inputArr[0].trim();
                let panels = inputArr.length >= 2 ? parseInt(inputArr[2]) : 1;
                item_obj = [id, inputArr[1], panels];
                if(inputArr.length > 3) {
                    // Panels were added
                    for(let i=3; i<inputArr.length; i++) {
                        item_obj.push(inputArr[i]);
                    }
                }
            }
        }
        return item_obj;
    }
}

class panHandler {
    constructor(args) {
        this.map = args.map;
        this.start = false;
        this.shift = false;
    }
    mouseEvent(e) {
        if(e.originalEvent.button !== 0) {
            return;
        }
        let pos = {x:e.originalEvent.clientX,y:e.originalEvent.clientY};
        if(e.type === "mousemove") {
            if(this.shift === true && this.hasOwnProperty("start_node")) {
                this.drag(pos,e);
            }
            else {
                this.move(pos);
            }
        }
        else if(e.type === "mousedown"){
            this.start = pos;
            if(typeof($(e.target).attr("node_id"))!=="undefined") {
                if(this.shift===false) {
                    return;
                }
                this.start_node = $(e.target).attr("node_id");
                let coords = this.start_node.split("_");
                this.map.sel_a = {x:parseInt(coords[0]),y:parseInt(coords[1])};
                $("#"+this.start_node+"_ring").show();
            }
        }
        else if(e.type==="mouseup") {
            if(this.shift===true) {
                // Called when in panel creation time.
                if(this.hasOwnProperty("last_node")) {
                    let end_coords = this.last_node.split("_");
                    this.map.activate(parseInt(end_coords[0]),parseInt(end_coords[1]));
                    delete this.last_node;
                }
                else {
                    this.map.sel_a = false;
                    if(this.hasOwnProperty("start_node")) {
                        delete this.last_node;
                    }
                    $(".node_ring").hide();
                }
            }
            else {
                this.reset();
                // Called when the map is being zoomed or panned
                if(this.start!==false) {
                    let dx = pos.x - this.start.x;// - pos.x;
                    let dy = pos.y - this.start.y;// - pos.y;
                    this.map.dx = this.map.dx + dx;
                    this.map.dy = this.map.dy + dy;
                }
                this.start = false;
            }

        }
    }
    shiftHandler(e) {
        if(e.type==="keydown") {
            this.shift = true;
        }
        else {
            if(this.hasOwnProperty("start_node")) {
                delete this.start_node;
            }
            if(this.hasOwnProperty("last_node")) {
                delete this.last_node;
            }
            $(".node_ring").hide();
            this.shift = false;
        }
    }
    async drag(pos,e) {
        if(this.start!==false && this.map.dots===true) {
            let dx = pos.x - this.start.x;
            let dy = pos.y - this.start.y;
            let delta = Math.sqrt(dx**2 + dy**2);
            if(delta>=10) {
                let compare_dots = await this.findDot(pos,e);
                if(compare_dots===true) {
                    this.compareDot(this.start_node,this.last_node);
                }
            }
        }
    }
    async findDot(pos,e) {
        let match_nodes = new Set();
        let compare = false;
        if(this.hasOwnProperty("start_node")) {
            $("#"+this.start_node+"_ring").show();
        }
        if(typeof($(e.target).attr("node_id"))!=="undefined") {
            this.last_node = $(e.target).attr("node_id");
            $("#"+$(e.target).attr("node_id")+"_ring").show();
        }
        if(this.hasOwnProperty("start_node")) { 
            match_nodes.add(this.start_node);
        }

        if(this.hasOwnProperty("last_node")) {
            match_nodes.add(this.last_node);
            if(this.start_node!==this.last_node) {
                compare = true;
            }
        }
        $(".node_ring").each(function() {
            if(match_nodes.has($(this).attr("node_id"))!==true) {
                $(this).hide();
            }
        });
        if(compare===true) {
            return true;
        }
        else {
            return false;
        }
    }
    async compareDot(a,b) {
        // Check the start and most recent node to see if a valid line can be drawn between them.
        let start_coord = a.split("_");
        let end_coord = b.split("_");
        if(start_coord[0]===end_coord[0]) {
            // Start and end are on the same horizontal plane.
            //console.log("vertical");
        }
        else if(start_coord[1]===end_coord[1]) {
            //console.log("horizontal");
        }
    }
    move(pos) {
        let m = this.map.allocator.map_dom;
        if(this.start !== false) {
            // Determine the offsets from the original event.
            let dx = pos.x - this.start.x;// - pos.x;
            let dy = pos.y - this.start.y;// - pos.y;
            $(m).css({"left":this.map.dx+dx,"top":this.map.dy+dy});
        } 
    }
    zoom(dir="out") {
        let m = this.map.allocator.map_dom;
        if(dir===false) {
            // If this is false, we're going to reset the zoom.
            this.map.dx = 0; // Reset the map delta (x) to 0
            this.map.dy = 0; // Reset the map delta (y) to 0
            $(m).css({"transform":"scale(1.0)","left":this.map.dx,"top":this.map.dy});
        }
        if(dir==="out") {
            this.start = false;
            if(this.map.zoom>1) {
                this.map.zoom = this.map.zoom - 1;
            }
        }
        else {
            this.start = false;
            this.map.zoom = this.map.zoom + 1;
            $(m).css({"transform":"scale("+this.map.zoom+")"});
        }
        if(this.map.zoom>1) {
            $(m).css({"transform":"scale("+this.map.zoom+")"});
            $(this.map.allocator.zoom["out"]).removeClass("button_disabled");
        }
        else {
            this.map.dx = 0;
            this.map.dy = 0;
            this.map.zoom = 1;
            $(this.map.allocator.zoom["out"]).addClass("button_disabled");
            $(m).css({"transform":"scale(1.0)","left":0,"top":0});
        }
    }
    reset() {
        if(this.hasOwnProperty("start_node")) { delete this.start_node; }
        if(this.hasOwnProperty("last_node")) { delete this.last_node; }
    }
}

class allocator {
    constructor(args) {
        this.map;
        this.logic;
        this.container;
        this.container_top;
        this.map_container_dom;
        this.map_dom;
        this.zoom;
        this.mode = "normal";
    }
    async createVisualStructure() {
        if(typeof(this.container) === "undefined") { return; }
        $(this.container).empty();
        let map_parent = this.map;
        let interactor_parent = this.map.interactor;
        let serializer_parent = this.serializer;

        // This function will build the DOM elements and provide the visual structure for the allocator.
        let main_container = $(this.container); 
        let t = $("<div />",{"class":"allocator_top"}); // Flex container for the map and artist list.
        this.container_top = t;

        let map_container_dom = $("<div />",{"class":"allocator_map_container","id":"show_map_container","attr":{"draggable":"false"}});
        let map_dom = $("<div />",{"class":"allocator_map","id":"show_map","attr":{"draggable":"false"}});
        let zoom_out = $("<div />",{"class":"btn-secondary zoom button_disabled","id":"zoom_out","text":"-","css":{"left":"0.3rem","top":"3rem"}});
        let zoom_in = $("<div />",{"class":"btn-secondary zoom","id":"zoom_out","text":"+","css":{"left":"0.3rem","top":"5.2rem"}});
        let label_dom = $("<div />",{"class":"face_label","id":"label_maker","css":{"top":"7.6rem","left":"0.3rem"}});
        let label_face_dom = $("<span />",{"id":"label_face"});
        let label_face_input_dom = $("<input />",{"id":"label_entry","class":"label_maker","attr":{"type":"text"}});
        $(label_face_input_dom).on("change",{arg1:map_parent},function(e) {
            e.data.arg1.applyLabel();
        })
        $(label_dom).append(label_face_dom);
        $(label_dom).append($("<span />",{"text":" label: "}));
        $(label_dom).append(label_face_input_dom); 
        this.label = {"label":label_dom,"face":label_face_dom,"input":label_face_input_dom};
        $(label_dom).hide();
        this.zoom = {"in":zoom_in,"out":zoom_out};
        this.map_dom = map_dom;
        this.map_container_dom = map_container_dom;
        $(map_container_dom).append(map_dom);
        
        // Bind the events used for map dragging.
        $(map_dom).on("mousedown", function(e) { interactor_parent.mouseEvent(e); });
        $(map_dom).on("mouseup", function(e) { interactor_parent.mouseEvent(e); });
        $(map_dom).on("mousemove", function(e) { interactor_parent.mouseEvent(e); });

        // Bind the events used for map zooming.
        $(zoom_in).on("click",function() { interactor_parent.zoom("in"); });
        $(zoom_out).on("click",function() { interactor_parent.zoom("out"); });

        t.append($(label_dom));
        t.append($(map_container_dom));
        t.append($(zoom_out));
        t.append($(zoom_in));

        // Create artist list container

        let side_panel = $("<div />",{"class":"allocator_side"});
        let assigned_artists = $("<div />",{"class":"artist_list"});
        let unassigned_artists = $("<div />",{"class":"artist_list"});
        let explanation = $("<p />", {"text": "Click on an artist name below to assign or unassign panels manually."});
        $(side_panel).append(explanation);
        $(side_panel).append(assigned_artists);
        $(side_panel).append(unassigned_artists);
        this.artists = {"assigned": assigned_artists, "unassigned": unassigned_artists};
        this.artist_list = side_panel;
        t.append($(side_panel));

        // Create controls

        let control_container = $("<div />",{"class":"controls d-flex gap-1"});
        let load_save = $("<div />",{"class":"btn btn-primary","text":"Load/Save"});
        let modify = $("<div />",{"class":"btn btn-secondary","text":"Modify Layout"});
        let rename = $("<div />",{"class":"btn btn-outline-secondary","text":"Modify Labels"});
        let save_layout = $("<div />",{"class":"btn btn-outline-primary","text":"Export Layout as JSON"});
        let assign = $("<div />",{"class":"btn btn-success","text":"Assign All Artists"});
        let assign_single = $("<div />",{"class":"btn btn-success","text":"Assigning Artist: "});
        let unassign_single = $("<div />",{"class":"btn btn-warning","text":"Unassign All for Artist"});
        let recalculate = $("<div />",{"class":"btn btn-info","text":"Recalculate Free Space"});
        $(rename).hide();
        $(assign_single).hide();
        $(recalculate).hide();
        let allocator = this;
        $(control_container).append(load_save);
        $(control_container).append(modify);
        $(control_container).append(rename);
        $(control_container).append(save_layout);
        $(control_container).append(assign);
        $(control_container).append(assign_single);
        $(control_container).append(unassign_single);
        $(control_container).append(recalculate);

        t.append($(control_container));

        // Create map keys

        let map_key_container = $("<div />",{"class":"map_key"});
        let legend = [
            ["Unassigned Panel","var(--inner-border-color)","key_pair normal_key"],
            ["New Panel (requires recalculation)","var(--created-border)","key_pair normal_key"],
            ["Allocated Panel","var(--selected-border)","key_pair normal_key"],
            ["Selected Panel","var(--selected-artist)","key_pair normal_key"],
            ["Valid Panel to be Allocated","var(--available-border)","key_pair build_key",true]
        ]
        for(let k in legend) {
            let key_pair = $("<div />",{"class":legend[k][2]});
            let key_color = $("<div />",{"class":"key_color","css":{"background-color":legend[k][1]}});
            let key_text = $("<div />",{"class":"key_explanation","text":legend[k][0]});
            if(legend[k].length>3) {
                if(legend[k][3]===true) {
                    // should start hidden.
                    $(key_pair).hide();
                }
            }
            $(key_pair).append(key_color);
            $(key_pair).append(key_text);
            $(map_key_container).append(key_pair);
        }

        $(main_container).append(t);
        $(main_container).append(map_key_container);

        // Create load area

        let load = $("<div />",{"class":"allocator_side"});
        let load_text = $("<textarea />",{"class":"load_area"});
        let upload_button = $("<a />",{"class":"btn btn-primary","css":{"margin-bottom":"1rem"},"text":"Upload"});
        let load_button = $("<div />",{"class":"btn btn-secondary","css":{"margin-bottom":"1rem"},"text":"Load Assignments"});
        let load_file = $("<input />",{"class":"","css":{"margin-bottom":"1rem"},attr:{"type":"file"}});
        let save_button = $("<div />",{"class":"btn btn-success","css":{"margin-bottom":"1rem"},"text":"Save Current Assignment"});
        $(load).append(upload_button);
        //$(load).append(load_file);
        $(load).append(load_button);
        $(load).append(save_button);
        $(load).append(load_text);
        this.artist_loader = load;
        this.load_src = load_text;
        this.file_loader = load_file;
        $(load).hide();
        t.append(load);

        // Bind event handlers for all buttons.

        $(this.file_loader).on("change", {arg1: allocator, arg2: "artist_loader"},function(e) { e.data.arg1.inputHandler(e.data.arg2); });

        this.buttons = {"load_save": load_save, "modify": modify, "rename": rename, "assign": assign, "assign_single": assign_single,
            "recalculate": recalculate, "load": load_button, "save": save_button, "unassign_single": unassign_single, "save_layout": save_layout,
            "upload": upload_button};
        for(let k in this.buttons) {
            $(this.buttons[k]).on("click",{arg1: allocator, arg2: k},function(e) { e.data.arg1.buttonHandler(e.data.arg2) });
        }

        return true;
    }

    async inputHandler(b) {
        if(b === "artist_loader") {
            if(this.serializer.input !== false) {
                this.mode = "normal";
                $(this.artist_list).show();
                $(this.artist_loader).hide();
                let loaded = await this.serializer.deserializeCSV();
                if(loaded===true) {
                    //console.log("Loaded from CSV");
                    this.logic.buildSections();
                    this.logic.assignAll();
                    //console.log("input handler")
                    this.assignmentVisibility();
                }
            }
        }
    }

    async buttonHandler(b) {
        let b_obj = this.buttons[b];
        let b_rel = []; // Buttons to show along side this one if active.
        if(b == "modify") {
            b_rel = ["rename", "load_save", "assign", "assign_single", "recalculate", "save_layout"];
            for(let k in b_rel) {
                $(this.buttons[b_rel[k]]).hide();
            }
            if(this.map.dots === true) {
                // Dots are currently shown; need to be hidden.
                this.map.hideDots();
                $(".normal_key").show();
                $(".build_key").hide();
                $(this.buttons["load_save"]).show();
                //console.log("button handler modify")
                this.assignmentVisibility();
                $(b_obj).text("Modify Layout");
            } else {
                this.map.showDots();
                $(".normal_key").hide();
                $(".build_key").show();
                $(b_obj).text("Done Modifying");
            }
        }
        else if(b === "rename") {
            b_rel = ["modify", "load_save", "assign"];
            if(map.labels === false) {
                for(let k in b_rel) {
                    $(this.buttons[b_rel[k]]).hide();
                }
                $(this.label["label"]).show();
                $(b_obj).text("Done Labeling");
            } else {
                $(this.label["label"]).hide();
                $(this.label["face"]).html("");
                $(this.label["input"]).val("");
                $(b_obj).text("Modify Labels");
                for(let k in b_rel) {
                    $(this.buttons[b_rel[k]]).show();
                }
            }
            this.map.doLabels();
        }
        else if(b === "assign_single") {
            this.logic.manual_assignee = false;
            b_rel = ["load_save","modify_layout"];
            $(b_obj).hide();
            for(let k in b_rel) {
                $(this.buttons[b_rel[k]]).show();
            }
            this.logic.artistList();
            this.logic.shadeByUse();
            //console.log("button handler single assign")
            this.assignmentVisibility();
        }
        else if(b === "unassign_single") {
            this.logic.clearAssignment(this.logic.manual_assignee);
            //console.log("button handler single unassign")
            this.assignmentVisibility();
        }
        else if(b === "recalculate") {
            this.logic.buildSections();
        }
        else if(b === "assign") {
            this.logic.assignAll();
        }
        else if(b === "load_save") {
            b_rel = ["rename","assign","assign_single","recalculate","modify","save_layout"];
            if(this.mode==="normal") {
                this.mode = "load";
                for(let k in b_rel) {
                    $(this.buttons[b_rel[k]].hide());
                }
                $(this.artist_list).hide();
                $(this.artist_loader).show();
                $(this.buttons["save_layout"]).show();
            }
            else {
                this.mode = "normal";
                $(this.artist_list).show();
                $(this.artist_loader).hide();
                //console.log("button handler load save")
                this.assignmentVisibility();
            }
        }
        else if(b === "load") {
            this.mode = "normal";
            $(this.artist_list).show();
            $(this.artist_loader).hide();
            let loaded = await this.serializer.deserialize();
            if(loaded===true) {
                this.logic.buildSections();
                this.logic.assignAll();
                //console.log("load")
                this.assignmentVisibility();
            }
        }
        else if(b==="save_layout") {
            if(this.hasOwnProperty("layout_serializer")) {
                this.layout_serializer.serialize("self");
            }
        }
        else if(b==="save") {
            this.serializer.serialize("self",true);
        }
        else if(b === "upload") {
            this.serializer.serialize("server", true);
        }
    }

    async assignmentVisibility() {
        //console.log("checking visibility")
        let has_manual_assignee = this.logic.hasOwnProperty("manual_assignee") ? this.logic.manual_assignee : false;
        if(has_manual_assignee === "labels") {
            // Nothing to do, buttons are already handled elsewhere
        } else if(has_manual_assignee !== false && this.logic.assignments[this.logic.manual_assignee]) {
            $(this.buttons["assign_single"]).show();
            if(this.logic.assignments[this.logic.manual_assignee].panels.size>0) {
                $(this.buttons["unassign_single"]).html("Unassign All for "+this.logic.assignments[this.logic.manual_assignee].name)
                $(this.buttons["unassign_single"]).show();
            }
            else {
                $(this.buttons["unassign_single"]).hide();
            }
            
            $(this.buttons["assign"]).hide();
            $(this.buttons["load_save"]).hide();
            $(this.buttons["modify"]).hide();
            $(this.buttons["rename"]).hide();
            $(this.buttons["save_layout"]).hide();
        } else {
            $(this.buttons["load_save"]).show();
            $(this.buttons["modify"]).show();
            $(this.buttons["save_layout"]).hide();
            $(this.buttons["assign_single"]).hide();
            $(this.buttons["unassign_single"]).hide();
            if(this.logic.needs_recalculation===false) {
                $(this.buttons["rename"]).show();
                $(this.buttons["assign"]).show();
                $(this.buttons["recalculate"]).hide();
            }
            else {
                $(this.buttons["rename"]).hide();
                $(this.buttons["assign"]).hide();
                $(this.buttons["recalculate"]).show();
            }
        }
    }
    async emptyVisualStructure() {
        const dom_keys = new Set(["label","zoom","map_dom","map_container_dom","artists"]);
        for(let k of dom_keys) {
            if(this.hasOwnProperty(k)) { delete this[k]; }
        }
        $(this.container).empty();
        return true;
    }

    async reinitialize() {
       
        let clear = await this.emptyVisualStructure();
        if(clear===true) {
            let reinit = await this.createVisualStructure();
            if(reinit===true) { 
                this.map.createMap();
                this.map.panels = {};
                this.map.face_ids = {};
                this.map.face_names = {};
                doPreload();
                this.logic.buildSections();
            }
        }
    }
}
